#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pygame
import time
import sys
from spherov2 import scanner
from spherov2.types import Color
from spherov2.sphero_edu import SpheroEduAPI
from spherov2.commands.power import Power
import math

'''
SB-9DD8 1
SB-2BBE 2
SB-27A5 3
SB-81E0 4
SB-7740 5
'''

# ======= TUNEERBARE CONSTANTEN (TRAAG + GEEN AUTO-0) =======
TILE_CM = 50.0          # 1 tegel = 50 cm
RUN_SPEED = 60          # traag (0..255)
SPEED_CM_PER_S = 30.0   # schatting cm/s bij RUN_SPEED (pas aan op basis van test)
SAFETY = 0.95           # iets korter rijden om overshoot te beperken
HEADING_SETTLE = 0.30   # rustpauze na heading wissel, voorkomt wegkruipen
# ===========================================================

buttons = {
    '1': 0,
    '2': 1,
    '3': 2,
    '4': 3,
    'L1': 4,
    'L2': 6,
    'R1': 5,
    'R2': 7,
    'SELECT': 8,
    'START': 9
}

class SpheroController:
    def __init__(self, joystick, color, ball_number):
        self.toy = None
        self.speed = 50
        self.heading = 0
        self.base_heading = 0                 # jouw referentiehoek (handmatig via R1/L1)
        self.is_running = True
        self.calibration_mode = False
        self.joystick = joystick
        self.last_command_time = time.time()
        self.heading_reset_interval = 1
        self.last_heading_reset_time = time.time()
        self.threshold_accel_mag = 0.05
        self.collision_occurred = False
        self.color = color
        self.previous_button = 0              # belangrijk voor 'rising edge'
        self.number = ball_number
        self.gameStartTime = time.time()
        self.gameOn = False
        self.boosterCounter = 0
        self.calibrated = False

    # ---------- HELPER: joystick deadzone ----------
    def _dz(self, v, dz=0.15):
        return 0 if abs(v) < dz else v

    # ---------- AUTONOME HELPERS (geen auto-0) ----------
    def _tiles_to_seconds(self, tiles: float) -> float:
        cm = tiles * TILE_CM
        return (cm / max(1e-6, SPEED_CM_PER_S)) * SAFETY

    def _roll_rel(self, api, rel_heading_deg: int, tiles: float, speed: int = RUN_SPEED):
        """
        Rijd 'tiles' tegels op absolute heading = (base_heading + rel_heading_deg) % 360.
        Geen automatische 0; jij zet base_heading zelf met R1/L1 voor de start.
        """
        abs_heading = int((self.base_heading + rel_heading_deg) % 360)
        api.set_speed(0)                      # zeker stil voor headingwissel
        api.set_heading(abs_heading)
        time.sleep(HEADING_SETTLE)
        duration = self._tiles_to_seconds(tiles)
        api.roll(speed, abs_heading, duration)
        api.set_speed(0)
        time.sleep(0.15)                      # kort stabiliseren

    def run_first_L_shape(self, api):
        """4 tegels vooruit, 90° rechts, 4 tegels vooruit, stop (traag)."""
        print("\n--- AUTONOOM: 4→, 90° rechts, 4→ ---")
        t0 = time.time()
        # 1) 4 tegels vooruit
        self._roll_rel(api, 0, 4.0, RUN_SPEED)
        # 2) 90° rechts en 4 tegels
        self._roll_rel(api, -90, 4.0, RUN_SPEED)
        api.set_speed(0)
        print(f"KLAAR — duur: {time.time()-t0:.2f} s\n")

    # ---------- BATTERIJ/CONNECT ----------
    def discover_nearest_toy(self):
        try:
            toys = scanner.find_toys()
            if not toys:
                print("Geen Sphero's gevonden.")
                return
            self.toy = toys[0]
            print(f"Dichtstbijzijnde Sphero toy '{self.toy.name}' ontdekt.")
            return self.toy.name
        except Exception as e:
            print(f"Error no toys nearby: {e}")

    def discover_toy(self, toy_name):
        try:
            self.toy = scanner.find_toy(toy_name=toy_name)
            print(f"Sphero toy '{toy_name}' discovered.")
        except Exception as e:
            print(f"Error discovering toy: {e}")

    def connect_toy(self):
        if self.toy is not None:
            try:
                return SpheroEduAPI(self.toy)
            except Exception as e:
                print(f"Error connecting to toy: {e}")
        else:
            print("No toy discovered. Please run discover_toy() first.")
            return None

    def move(self, api, heading, speed):
        api.set_heading(heading)
        api.set_speed(speed)

    # ---------- (optioneel) oude kalibratie-functies laten staan, maar NIET gebruiken ----------
    def toggle_calibration_mode(self, api, Y):
        if not self.calibration_mode:
            self.enter_calibration_mode(api, Y)
        else:
            self.exit_calibration_mode(api)

    def enter_calibration_mode(self, api, X):
        api.set_speed(0)
        self.gameStartTime = time.time()
        self.calibration_mode = True
        self.gameOn = False
        api.set_front_led(Color(255, 0, 0))
        self.base_heading = api.get_heading()
        if X < -0.7:
            new_heading = self.base_heading - 5
        elif X > 0.7:
            new_heading = self.base_heading + 5
        else:
            new_heading = self.base_heading
        api.set_heading(new_heading)

    def exit_calibration_mode(self, api):
        self.calibrated = True
        self.calibration_mode = False
        self.gameOn = True
        self.boosterCounter = 0
        self.gameStartTime = time.time()
        api.set_front_led(Color(0, 255, 0))

    LED_PATTERNS = {1:'1',2:'2',3:'3',4:'4',5:'5'}

    def set_number(self, number):
        self.number = int(number)

    def display_number(self, api):
        number_char = self.LED_PATTERNS.get(self.number)
        if number_char:
            api.set_matrix_character(number_char, self.color)
        else:
            print(f"Error in matrix '{self.number}'")

    def print_battery_level(self, api):
        battery_voltage = Power.get_battery_voltage(self.toy)
        print(f"Battery status of {self.number}: {battery_voltage:.2f} V ")
        if (battery_voltage > 4.1):
            api.set_front_led(Color(r=0, g=255, b=0))
        if 3.9 < battery_voltage <= 4.1:
            api.set_front_led(Color(r=255, g=255, b=0))
        if 3.7 < battery_voltage <= 3.9:
            api.set_front_led(Color(r=255, g=100, b=0))
        if battery_voltage <= 3.7:
            api.set_front_led(Color(r=255, g=0, b=0))
        if battery_voltage < 3.5:
            sys.exit("Battery low — stop.")

    # ---------- MAIN LOOP ----------
    def control_toy(self):
        try:
            with self.connect_toy() as api:
                last_battery_print_time = time.time()
                self.set_number(self.number)
                self.display_number(api)

                # BELANGRIJK: GEEN automatische 0/kalibratie hier!
                # self.enter_calibration_mode(api, 0)
                # self.exit_calibration_mode(api)

                move_start_time = None

                while self.is_running:
                    pygame.event.pump()

                    # Batterij status af en toe
                    if time.time() - last_battery_print_time >= 30:
                        self.print_battery_level(api)
                        last_battery_print_time = time.time()

                    # Lees joystick (met deadzone)
                    X = self._dz(self.joystick.get_axis(0))
                    Y = self._dz(self.joystick.get_axis(1))

                    # --- KNOP 1: AUTONOME L-VORM (4→, rechts, 4→) ---
                    btn1 = self.joystick.get_button(buttons['1'])
                    if btn1 == 1 and self.previous_button == 0:
                        self.run_first_L_shape(api)
                    self.previous_button = btn1

                    # --- R1/L1: base_heading draaien in stappen van 45° (jij richt zelf) ---
                    if (self.joystick.get_button(buttons['R1']) == 1):
                        self.base_heading = (self.base_heading + 45) % 360
                        self.move(api, self.base_heading, 0)
                        time.sleep(0.25)

                    if (self.joystick.get_button(buttons['L1']) == 1):
                        self.base_heading = (self.base_heading - 45) % 360
                        self.move(api, self.base_heading, 0)
                        time.sleep(0.25)

                    # --- Optioneel: handmatig vooruit/achteruit met Y (traag) ---
                    if Y < -0.7:
                        if move_start_time is None:
                            move_start_time = time.time()
                            self.move(api, self.base_heading, 50)  # traag
                        else:
                            self.move(api, self.base_heading, 50)
                            if time.time() - move_start_time >= 1.0:
                                api.set_speed(0)
                                move_start_time = None
                    elif Y > 0.7:
                        self.move(api, (self.base_heading + 180) % 360, 40)
                    else:
                        api.set_speed(0)
                        move_start_time = None

                    # BELANGRIJK: GEEN automatische self.base_heading = api.get_heading()
                    # (anders 'kruipt' je 0-punt en draait hij een paar graden bij de start)

        finally:
            pygame.quit()

def main(toy_name=None, joystickID=0, playerID=1):
    pygame.init()
    pygame.joystick.init()

    num_joysticks = pygame.joystick.get_count()
    if num_joysticks == 0:
        print("No joysticks found.")
        return

    joystick = pygame.joystick.Joystick(joystickID)
    joystick.init()

    sphero_color = Color(255, 0, 0)
    sphero_controller = SpheroController(joystick, sphero_color, playerID)

    if toy_name is None:
        sys.exit("No toy name provided")

    sphero_controller.discover_toy(toy_name)

    if sphero_controller.toy:
        sphero_controller.control_toy()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python script.py <toy_name> <joystickNumber 0-1> <player 1-5>")
        sys.exit(1)

    toy_name = sys.argv[1]
    joystick = int(sys.argv[2])
    playerid = int(sys.argv[3])
    print(f"Try to connect to: {toy_name} with number {joystick} for player {playerid}")

    main(toy_name, joystick, playerid)
