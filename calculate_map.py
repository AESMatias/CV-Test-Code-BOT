import pydirectinput
import time
import os

def clear():
    os.system('cls' if os.name == 'nt' else 'clear')

clear()
print("\n--- PHASE 1: MINIMAP ---")

print("1. TOP Edge of Minimap (12:00)")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, mm_top = pydirectinput.position()
print(" OK.")

print("2. BOTTOM Edge of Minimap (06:00)")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, mm_bottom = pydirectinput.position()
print(" OK.")

print("3. LEFT Edge of Minimap (09:00)")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
mm_left, _ = pydirectinput.position()
print(" OK.")

print("4. RIGHT Edge of Minimap (03:00)")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
mm_right, _ = pydirectinput.position()
print(" OK.")

print("\n--- PHASE 2: HP BAR (RED) ---")
print("Point to the exact RED part (ignore the decorative frame)")

print("5. TOP Edge of Red Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, hp_top = pydirectinput.position()
print(" OK.")

print("6. BOTTOM Edge of Red Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, hp_bottom = pydirectinput.position()
print(" OK.")

print("7. LEFT Start of Red Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
hp_left, _ = pydirectinput.position()
print(" OK.")

print("8. RIGHT End of Red Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
hp_right, _ = pydirectinput.position()
print(" OK.")

print("\n--- PHASE 3: SP BAR (BLUE) ---")
print("9. TOP Edge of Blue Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, sp_top = pydirectinput.position()
print(" OK.")

print("10. BOTTOM Edge of Blue Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
_, sp_bottom = pydirectinput.position()
print(" OK.")

print("11. LEFT Start of Blue Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
sp_left, _ = pydirectinput.position()
print(" OK.")

print("12. RIGHT End of Blue Bar")
for i in range(3, 0, -1): print(f" {i}...", end='\r'); time.sleep(1)
sp_right, _ = pydirectinput.position()
print(" OK.")

mm_w = mm_right - mm_left
mm_h = mm_bottom - mm_top

hp_w = hp_right - hp_left
hp_h = hp_bottom - hp_top

sp_w = sp_right - sp_left
sp_h = sp_bottom - sp_top

print(f"MINIMAP_REGION = {{'top': {mm_top}, 'left': {mm_left}, 'width': {mm_w}, 'height': {mm_h}}}")
print(f"HP_REGION = {{'top': {hp_top}, 'left': {hp_left}, 'width': {hp_w}, 'height': {hp_h}}}")
print(f"SP_REGION = {{'top': {sp_top}, 'left': {sp_left}, 'width': {sp_w}, 'height': {sp_h}}}")
print("=================================================")
input("Press Enter to exit...")