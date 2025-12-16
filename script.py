import cv2
import numpy as np
import mss
import pydirectinput
import time
import math
import keyboard
import random
import os
import csv
from collections import deque
from datetime import datetime

# Screen zones - Need to adjust these if I change resolution
MINIMAP_REGION = {'top': 45, 'left': 901, 'width': 114, 'height': 114}
HP_REGION = {'top': 768, 'left': 59, 'width': 99, 'height': 11}
SP_REGION = {'top': 781, 'left': 60, 'width': 98, 'height': 9}
ITEM_SEARCH_REGION = {'top': 200, 'left': 200, 'width': 800, 'height': 400}
SCREEN_WIDTH = 1366 
SCREEN_HEIGHT = 768
DAMAGE_REGION = {'top': (SCREEN_HEIGHT // 2) - 150, 'left': (SCREEN_WIDTH // 2) - 100, 'width': 200, 'height': 200}

# Center vision area, ignoring UI elements on corners
VISION_3D_REGION = {'top': 100, 'left': 150, 'width': 1066, 'height': 500}

# ranges
MAP_ATTACK_RANGE = 45       
MAP_COMBAT_RANGE = 12       
MAP_ANCHOR_RANGE = 6        

# Screen pixel ranges for CV
SCREEN_COMBAT_RANGE = 80  
SCREEN_ANCHOR_RANGE = 35  

PLAYER_MASK_RADIUS = 7  

# Color filters (HSV)
# Minimap red dots
lower_red1 = np.array([0, 100, 100])
upper_red1 = np.array([10, 255, 255])
lower_red2 = np.array([160, 100, 100])
upper_red2 = np.array([180, 255, 255])

# Mob names pure Red only, ignoring Green/Level
lower_mob_text1 = np.array([0, 180, 100]) 
upper_mob_text1 = np.array([10, 255, 255])
lower_mob_text2 = np.array([170, 180, 100]) 
upper_mob_text2 = np.array([180, 255, 255])

# Damage numbers Yellow crit/normal
lower_yellow = np.array([20, 180, 180]) 
upper_yellow = np.array([40, 255, 255])

# Item pickup text
lower_text = np.array([0, 0, 0])
upper_text = np.array([180, 255, 60])

# Logging
CSV_FILE = "bot_log.csv"

# Global state tracking
potion_timers = {'hp': 0, 'sp': 0}
pickup_timer = 0
last_hp_check_time = time.time()
hp_history = [] 

current_panic_dir = []
panic_dir_change_time = 0

pydirectinput.PAUSE = 0.0
pydirectinput.FAILSAFE = False


class MovementMemory:
    # Tracks recent key presses to detect if we are "orbiting" a mob (dancing) without hitting
    def __init__(self):
        self.key_history = deque(maxlen=60) # Keeping roughly 1.5s history
        self.locked_mode = False
        self.lock_end_time = 0
        self.lock_keys = []

    def log_keys(self, keys):
        if not keys: 
            self.key_history.append("none")
        else:
            # Sort to treat ['w', 'a'] same as ['a', 'w']
            self.key_history.append("+".join(sorted(keys)))

    def check_orbit_dance(self, is_hitting):
        # Hitting resets everything, means movement is fine
        if is_hitting:
            self.key_history.clear()
            self.locked_mode = False
            return False

        # If already correcting, stick to it until timer ends
        if self.locked_mode:
            if time.time() > self.lock_end_time:
                self.locked_mode = False
                self.key_history.clear() 
            return True 

        # Need enough history to judge
        if len(self.key_history) < 40: return False

        # Check for diagonal spam (w+a, s+d, etc) without success
        diag_count = 0
        for k in self.key_history:
            if "+" in k and "space" not in k: 
                diag_count += 1
        
        # If >70% of recent moves are diagonals and we aren't hitting -> Stuck orbiting
        if diag_count > 30: 
            return True 
        
        return False

    def activate_correction(self, intended_keys):
        # Force a straight line movement to break the orbit circle
        self.locked_mode = True
        self.lock_end_time = time.time() + 1.5 
        
        new_keys = []
        # Prioritize vertical/horizontal cuts over diagonals
        if 'w' in intended_keys: new_keys = ['w']
        elif 's' in intended_keys: new_keys = ['s']
        elif 'a' in intended_keys: new_keys = ['a']
        elif 'd' in intended_keys: new_keys = ['d']
        
        if 'space' in intended_keys:
            new_keys.append('space')
            
        self.lock_keys = new_keys
        return new_keys

class MobBlacklist:
    # Short-term memory to ignore ghosts or unreachables on minimap
    def __init__(self):
        self.ignored_zones = [] 

    def add_ignore(self, dx, dy):
        duration = random.uniform(8.0, 10.0) # Ghost fade time approx 8-10s
        expire_time = time.time() + duration
        self.ignored_zones.append({'dx': dx, 'dy': dy, 'expire': expire_time})
        print(f"DEBUG: Ignoring zone ({dx}, {dy}) for {duration:.1f}s")

    def is_ignored(self, target_dx, target_dy):
        current_time = time.time()
        # Cleanup old
        self.ignored_zones = [z for z in self.ignored_zones if z['expire'] > current_time]
        
        for zone in self.ignored_zones:
            dist = math.sqrt((target_dx - zone['dx'])**2 + (target_dy - zone['dy'])**2)
            if dist < 15: return True # Ignore radius
        return False

class GameLogger:
    def __init__(self):
        self.headers = ['timestamp', 'hp_percent', 'dist_screen', 'hp_var', 
                        'damage_seen', 'orbit_breaker', 'current_state']
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, 'w', newline='') as f:
                csv.writer(f).writerow(self.headers)
    def log_step(self, data):
        with open(CSV_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([data.get(h, 0) for h in self.headers])

class GameState:
    def __init__(self):
        self.hp_history = deque(maxlen=40)
        self.max_hp_seen = 0 
        
    def sanitize_hp(self, raw_hp):
        # Fix potential OCR jitter or bar fill glitches
        if raw_hp > self.max_hp_seen: self.max_hp_seen = raw_hp
        if self.max_hp_seen == 0: return raw_hp
        
        # Smooth out 1% flickers
        if len(self.hp_history) > 0 and abs(raw_hp - self.hp_history[-1]) <= 1 and raw_hp < self.max_hp_seen:
            return self.hp_history[-1]
            
        return round((raw_hp / max(1, self.max_hp_seen)) * 100, 1)

    def calculate_metrics(self, current_hp):
        self.hp_history.append(current_hp)
        # HP variance tells us if we are taking sustained damage
        hp_variance = np.var(self.hp_history) if len(self.hp_history) > 5 else 0
        return hp_variance

def press_key_safe(key):
    pydirectinput.keyDown(key)
    time.sleep(0.05) 
    pydirectinput.keyUp(key)

def get_hp_exact(sct):
    # Pixel counting on HP bar for exact percentage
    img = np.array(sct.grab(HP_REGION))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    # Masking for red pixels
    mask = cv2.inRange(hsv, np.array([0, 70, 60]), np.array([10, 255, 255])) + \
           cv2.inRange(hsv, np.array([160, 70, 60]), np.array([180, 255, 255]))
    
    height, width = mask.shape
    current_width = 0
    mid_y = height // 2
    
    # Scanning middle line
    for x in range(width):
        if mask[mid_y, x] > 0: current_width += 1
        elif x + 2 < width and mask[mid_y, x+1] == 0 and mask[mid_y, x+2] == 0: break
    return int((current_width / width) * 100)

def get_sp_percent(sct):
    img = np.array(sct.grab(SP_REGION))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([90, 60, 60]), np.array([140, 255, 255]))
    return int((cv2.countNonZero(mask) / (img.shape[0]*img.shape[1])) * 100)

def manage_status(sct):
    global potion_timers, hp_history 
    current_time = time.time()
    
    hp_pct = get_hp_exact(sct)
    sp_pct = get_sp_percent(sct)

    if current_time - last_hp_check_time > 0.5:
        hp_history.append(hp_pct)
        if len(hp_history) > 4: hp_history.pop(0) 

    taking_damage = False
    if len(hp_history) > 0:
        max_recent_hp = max(hp_history)
        if hp_pct < max_recent_hp - 3: taking_damage = True

    # Auto-pottioon logic
    if hp_pct < 70 and current_time > potion_timers['hp']:
        press_key_safe('f1') 
        potion_timers['hp'] = current_time + 1.0
    if sp_pct < 20 and current_time > potion_timers['sp']:
        press_key_safe('f2')
        potion_timers['sp'] = current_time + 1.5
    
    return hp_pct, taking_damage

def get_map_target(sct, blacklist):
    # Minimap radar logic
    img_mini = np.array(sct.grab(MINIMAP_REGION))
    hsv_mini = cv2.cvtColor(img_mini, cv2.COLOR_BGRA2BGR)
    hsv_mini = cv2.cvtColor(hsv_mini, cv2.COLOR_BGR2HSV)
    
    mask_red = cv2.inRange(hsv_mini, lower_red1, upper_red1) + cv2.inRange(hsv_mini, lower_red2, upper_red2)
    
    mini_cx = MINIMAP_REGION['width'] // 2
    mini_cy = MINIMAP_REGION['height'] // 2
    
    # Remove player arrow from mask minimap
    cv2.circle(mask_red, (mini_cx, mini_cy), PLAYER_MASK_RADIUS, 0, -1)
    mask_red = cv2.dilate(mask_red, None, iterations=2)
    
    contours, _ = cv2.findContours(mask_red, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    closest_dx, closest_dy = 0, 0
    min_dist = 9999
    found = False
    
    for cnt in contours:
        if cv2.contourArea(cnt) < 1: continue
        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            dx = cx - mini_cx
            dy = cy - mini_cy
            
            if blacklist.is_ignored(dx, dy): continue
            
            dist = math.sqrt(dx**2 + dy**2)
            if dist < min_dist:
                min_dist = dist
                closest_dx = dx
                closest_dy = dy
                found = True
                
    if found: return closest_dx, closest_dy, min_dist
    return 0, 0, 9999

def get_screen_target(sct):
    # 3D vision logic for ffinding mob names
    img = np.array(sct.grab(VISION_3D_REGION))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    
    # Filter strictly for RED nnames, skipping green levels
    mask1 = cv2.inRange(hsv, lower_mob_text1, upper_mob_text1)
    mask2 = cv2.inRange(hsv, lower_mob_text2, upper_mob_text2)
    mask = mask1 + mask2
    
    # Dilate horizontally to connect letters into a single blob
    kernel = np.ones((2, 10), np.uint8) 
    mask = cv2.dilate(mask, kernel, iterations=1)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    center_x = VISION_3D_REGION['width'] // 2
    center_y = VISION_3D_REGION['height'] // 2
    
    closest_dx, closest_dy = 0, 0
    min_dist = 9999
    found = False
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 50 or area > 3000: continue
        
        x, y, w, h = cv2.boundingRect(cnt)
        blob_cx = x + w // 2
        blob_cy = y + h # Bottom of text is roughly where mob feet are
        
        dx = blob_cx - center_x
        dy = blob_cy - center_y
        dist = math.sqrt(dx**2 + dy**2)
        
        if dist < min_dist:
            min_dist = dist
            closest_dx = dx
            closest_dy = dy
            found = True
            
    if found: return closest_dx, closest_dy, min_dist
    return 0, 0, 9999

def detect_damage_numbers(sct_img):
    # Checking for yellow numbers indicating hits NO ANOTHER COLOR!
    img = np.array(sct_img)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    return cv2.countNonZero(mask) > 5

def manage_pickup(sct, force=False):
    global pickup_timer
    current_time = time.time()
    
    if current_time - pickup_timer > 2.0 or force:
        press_key_safe('z')
        pickup_timer = current_time
        return
        
    try:
        # Check if items on ground (text labels)
        img = np.array(sct.grab(ITEM_SEARCH_REGION))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        hsv = cv2.cvtColor(hsv, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, lower_text, upper_text)
        if cv2.countNonZero(mask) > 150: 
            if random.random() < 0.2: press_key_safe('z')
    except: pass

def update_keys(keys_to_press):
    all_keys = ['w', 's', 'a', 'd', 'space']
    for k in keys_to_press: pydirectinput.keyDown(k)
    for k in all_keys:
        if k not in keys_to_press: pydirectinput.keyUp(k)

def process_bot():
    global current_panic_dir, panic_dir_change_time
    
    # Init lightweight modules
    logger = GameLogger()
    state_manager = GameState()
    blacklist = MobBlacklist()
    move_mem = MovementMemory()
    
    last_print = time.time()
    is_attacking = False
    escape_mode = False
    escape_end_time = 0
    
    last_successful_hit_time = time.time() 
    no_hit_duration = 0.0
    last_combat_activity_time = 0

    stuck_phase = 0 
    stuck_monitor_start = time.time()
    stuck_phase_end_time = 0
    stuck_run_direction = []

    exploring_mode = False
    explore_dir_change_time = 0
    explore_current_dir = []

    with mss.mss() as sct:
        while True:
            # Emergency exit
            if keyboard.is_pressed('F10'):
                update_keys([])
                print("Exit.")
                break
            
            try:
                loop_start = time.time()

                # 1. Perception Layer
                hp_pct, taking_damage_flag = manage_status(sct)
                dealing_damage_visual = detect_damage_numbers(sct.grab(DAMAGE_REGION))
                
                map_dx, map_dy, map_dist = get_map_target(sct, blacklist)
                scr_dx, scr_dy, scr_dist = get_screen_target(sct)
                
                target_source = "NADA"
                final_dx, final_dy, final_dist = 0, 0, 9999
                
                # Priority: Screen Target > Map Target
                if scr_dist < 9000:
                    target_source = "PANTALLA"
                    final_dx, final_dy = scr_dx, scr_dy
                    final_dist = scr_dist
                    combat_range = SCREEN_COMBAT_RANGE
                    anchor_range = SCREEN_ANCHOR_RANGE
                elif map_dist < 9000:
                    target_source = "MAPA"
                    final_dx, final_dy = map_dx, map_dy
                    final_dist = map_dist
                    combat_range = MAP_COMBAT_RANGE
                    anchor_range = MAP_ANCHOR_RANGE
                
                # 2. Stats & Status
                real_hp = state_manager.sanitize_hp(hp_pct)
                hp_variance = state_manager.calculate_metrics(real_hp)
                is_taking_real_damage = taking_damage_flag or hp_variance > 2.0
                is_hitting_effectively = dealing_damage_visual

                if is_taking_real_damage or is_hitting_effectively:
                    last_combat_activity_time = time.time()
                    last_successful_hit_time = time.time()
                    no_hit_duration = 0.0
                    stuck_phase = 0
                    escape_mode = False
                    exploring_mode = False

                if is_attacking and not is_hitting_effectively:
                    no_hit_duration = time.time() - last_successful_hit_time
                else:
                    no_hit_duration = 0.0

                hitting_air = no_hit_duration > 0.5
                current_action_label = "IDLE"

                # 3. Decision Logic: Anti-Orbit Check
                should_break_orbit = move_mem.check_orbit_dance(is_hitting_effectively)

                # 4. Ghost Detection (Map only)
                if no_hit_duration > 5.0 and target_source == "MAPA":
                    blacklist.add_ignore(final_dx, final_dy)
                    escape_mode = True
                    escape_end_time = time.time() + 1.5
                    last_successful_hit_time = time.time()

                manage_pickup(sct, force=(target_source == "NADA"))
                active_keys = []

                if should_break_orbit and target_source != "NADA":
                    intended_keys = []
                    if final_dist < anchor_range: intended_keys.append('space')
                    else:
                        if final_dy < -5: intended_keys.append('w')
                        elif final_dy > 5: intended_keys.append('s')
                        if final_dx < -5: intended_keys.append('a')
                        elif final_dx > 5: intended_keys.append('d')
                        if final_dist <= combat_range: intended_keys.append('space')
                    
                    active_keys = move_mem.activate_correction(intended_keys)
                    current_action_label = "FIX_ORBIT"

                elif stuck_phase > 0:
                    if stuck_phase == 1: 
                         if time.time() - stuck_monitor_start > 4.0:
                             stuck_phase = 2
                             stuck_phase_end_time = time.time() + random.uniform(1.0, 1.5)
                    elif stuck_phase == 2: 
                         current_action_label = "WAIT_STUCK"
                         if time.time() > stuck_phase_end_time:
                             stuck_phase = 3
                             stuck_phase_end_time = time.time() + random.uniform(3.0, 5.0)
                             stuck_run_direction = [random.choice(['w', 'a', 's', 'd'])]
                    elif stuck_phase == 3: 
                         current_action_label = "RUN_STUCK"
                         active_keys = stuck_run_direction
                         if time.time() > stuck_phase_end_time:
                             stuck_phase = 0
                             stuck_monitor_start = time.time()

                elif is_taking_real_damage and target_source == "NADA":
                    is_attacking = True
                    current_action_label = "BLIND_DEFENSE"
                    active_keys.append('space') 
                    if random.random() < 0.3: active_keys.append('a') 

                elif target_source != "NADA":
                    exploring_mode = False
                    
                    if escape_mode:
                        is_attacking = False
                        current_action_label = "SEARCHING"
                        if time.time() - panic_dir_change_time > 0.4:
                            current_panic_dir = random.choice([['a'], ['d'], ['w', 'a'], ['s']])
                            panic_dir_change_time = time.time()
                        active_keys = current_panic_dir
                        if time.time() > escape_end_time: escape_mode = False
                    
                    else:
                        if final_dist < anchor_range:
                            active_keys.append('space')
                            is_attacking = True
                            current_action_label = f"ATK_STATIC ({target_source})"
                        elif final_dist <= combat_range * 4: 
                             is_attacking = (final_dist <= combat_range)
                             current_action_label = f"COMBAT ({target_source})"
                             if is_attacking: active_keys.append('space')
                             
                             if final_dy < -5: active_keys.append('w')
                             elif final_dy > 5: active_keys.append('s')
                             if final_dx < -5: active_keys.append('a')
                             elif final_dx > 5: active_keys.append('d')
                        else:
                             is_attacking = False
                             current_action_label = f"CHASING ({target_source})"
                             if final_dy < -5: active_keys.append('w')
                             elif final_dy > 5: active_keys.append('s')
                             if final_dx < -5: active_keys.append('a')
                             elif final_dx > 5: active_keys.append('d')

                else: 
                    is_attacking = False
                    exploring_mode = True
                    current_action_label = "EXPLORING"
                    if time.time() - explore_dir_change_time > random.uniform(2.0, 3.0):
                        explore_current_dir = random.choice([['w'], ['s'], ['a'], ['d']])
                        explore_dir_change_time = time.time()
                    active_keys = explore_current_dir

                # Register keys for analysis and execute
                move_mem.log_keys(active_keys)
                update_keys(active_keys)

                # - CONSOLE OUTPUT-
                if time.time() - last_print > 0.2:
                    dist_str = f"{int(final_dist)}" if final_dist < 9000 else "-"
                    dmg_out = "HIT!" if is_hitting_effectively else "    "
                    print(f"Est: {current_action_label:<18} | HP: {real_hp:>3}% | {dmg_out} | Dist: {dist_str:>3}")
                    last_print = time.time()
                
                log_data = {'timestamp': datetime.now().isoformat(), 'hp_percent': real_hp, 'dist_screen': scr_dist, 'damage_seen': 1 if is_hitting_effectively else 0, 'current_state': current_action_label}
                logger.log_step(log_data)

                elapsed = time.time() - loop_start
                time.sleep(max(0, 0.025 - elapsed))
                
            except Exception as e:
                print(f"Error Loop: {e}")
                pass

    cv2.destroyAllWindows()

if __name__ == "__main__":
    time.sleep(1)
    process_bot()