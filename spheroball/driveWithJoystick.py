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

# ======= TUNEERBARE CONSTANTEN =======
RUN_SPEED = 30          # TRAGE snelheid (0..255)
SPEED_CM_PER_S = 20.0    # schatting cm/s bij RUN_SPEED op jullie vloer
SAFETY = 0.40            # iets korter rijden om overshoot te beperken
HEADING_SETTLE = 0.10    # iets langer wachten na het draaien
SCALE = 0.5              # *** ALLE AFSTANDEN GEDEELD DOOR 2 ***
# =====================================

buttons = {
    '1': 0, '2': 1, '3': 2, '4': 3,
    'L1': 4, 'R1': 5, 'L2': 6, 'R2': 7,
    'SELECT': 8, 'START': 9
}

class SpheroController:
    def __init__(self, joystick, color, ball_number):
        self.toy = None
        self.speed = 50
        self.heading = 0
        self.base_heading = 0
        self.is_running = True
        self.calibration_mode = False
        self.joystick = joystick
        self.last_command_time = time.time()
        self.heading_reset_interval = 1
        self.last_heading_reset_time = time.time()
        self.threshold_accel_mag = 0.05
        self.collision_occurred = False
        self.color = color
        self.previous_button = 0
        self.number = ball_number
        self.gameStartTime = time.time()
        self.gameOn = False
        self.boosterCounter = 0
        self.calibrated = False

    # ---------- AUTONOME HELPERS ----------
    def meters_to_seconds(self, meters: float) -> float:
        cm = meters * 100.0
        return (cm / max(1e-6, SPEED_CM_PER_S)) * SAFETY

    def roll_forward_rel(self, api, rel_heading_deg: int, meters: float, speed: int = RUN_SPEED):
        abs_heading = int((self.base_heading + rel_heading_deg) % 360)
        api.set_heading(abs_heading)
        time.sleep(HEADING_SETTLE)
        duration = self.meters_to_seconds(meters * SCALE)  # afstand gehalveerd
        api.roll(speed, abs_heading, duration)
        api.set_speed(0)
        time.sleep(0.12)

    def build_segments(self):
        """
        JOUW TRAJECT (wijzerszin) — afstanden worden nog eens vermenigvuldigd met SCALE=0.5:
        2.8 m → rechts 2.5 → rechts 1.0 → links 2.3 → links 1.3 → rechts 2.5 → rechts 3.0 → stop
        """
        seg = []
        heading = 0  # start vooruit

        def fwd(m): seg.append(("→", heading, m))
        def right():
            nonlocal heading
            heading = (heading - 90) % 360
        def left():
            nonlocal heading
            heading = (heading + 90) % 360

        fwd(2.8)
        right(); fwd(2.5)
        right(); fwd(1.0)
        left();  fwd(2.3)
        left();  fwd(1.3)
        right(); fwd(2.5)
        right(); fwd(3.0)
        return seg

    def run_autonomous_lap(self, api):
        print("\n--- AUTONOME RONDE (TRAAG & 1/2 AFSTAND) ---")
        start_base = self.base_heading
        t0 = time.time()
        for _, rel_h, meters in self.build_segments():
            abs_h = (start_base + rel_h) % 360
            print(f"heading={abs_h:3.0f}°, afstand={meters*SCALE:.2f} m (geschaald)")
            self.roll_forward_rel(api, rel_h, meters, RUN_SPEED)
        api.set_speed(0)
        print(f"FINISH — tijd: {time.time() - t0:.2f} s\n")

    # ---------- ORIGINELE FUNCTIES ----------
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

    def enter_calibration_mode(self, api, X):
        api.set_speed(0)
        self.gameStartTime = time.time()
        self.calibration_mode = True
        self.gameOn = False
        api.set_front_led(Color(255, 0, 0))
        self.base_heading = api.get_heading()
        if   X < -0.7: new_heading = self.base_heading - 5
        elif X >  0.7: new_heading = self.base_heading + 5
        else:          new_heading = self.base_heading
        api.set_heading(new_heading)

    def exit_calibration_mode(self, api):
        self.calibrated = True
        self.calibration_mode = False
        self.gameOn = True
        self.boosterCounter = 0
        self.gameStartTime = time.time()
        api.set_front_led(Color(0, 255, 0))

    LED_PATTERNS = {1:'1',2:'2',3:'3',4:'4',5:'5'}
    def set_number(self, number): self.number = int(number)
    def display_number(self, api):
        ch = self.LED_PATTERNS.get(self.number)
        if ch: api.set_matrix_character(ch, self.color)

    def print_battery_level(self, api):
        v = Power.get_battery_voltage(self.toy)
        print(f"Battery: {v:.2f} V")
        if v > 4.1: api.set_front_led(Color(0,255,0))
        elif v > 3.9: api.set_front_led(Color(255,255,0))
        elif v > 3.7: api.set_front_led(Color(255,100,0))
        else: api.set_front_led(Color(255,0,0))
        if v < 3.5: sys.exit("Battery low — stop.")

    def control_toy(self):
        try:
            with self.connect_toy() as api:
                last_battery_print = time.time()
                self.set_number(self.number)
                self.display_number(api)
                self.enter_calibration_mode(api, 0)
                self.exit_calibration_mode(api)

                move_start_time = None

                while self.is_running:
                    pygame.event.pump()
                    if time.time() - last_battery_print >= 30:
                        self.print_battery_level(api)
                        last_battery_print = time.time()

                    # --- KNOP 1: AUTONOME, TRAGE, GEHALVEERDE RONDE ---
                    btn1 = self.joystick.get_button(buttons['1'])
                    if btn1 == 1 and self.previous_button == 0:
                        self.run_autonomous_lap(api)
                    self.previous_button = btn1

                    # R1/L1: heading stapjes (niet aangepast)
                    if self.joystick.get_button(buttons['R1']) == 1:
                        self.base_heading = (self.base_heading + 45) % 360
                        self.move(api, self.base_heading, 0)
                        time.sleep(0.3)
                    if self.joystick.get_button(buttons['L1']) == 1:
                        self.base_heading = (self.base_heading - 45) % 360
                        self.move(api, self.base_heading, 0)
                        time.sleep(0.3)

                    # (optioneel) manuele Y-rijden — je mag dit weghalen als het stoort
                    Y = self.joystick.get_axis(1)
                    if Y < -0.7:
                        if move_start_time is None:
                            move_start_time = time.time()
                            self.move(api, self.base_heading, 60)  # trager
                        else:
                            self.move(api, self.base_heading, 60)
                            if time.time() - move_start_time >= 1:
                                api.set_speed(0); move_start_time = None
                    elif Y > 0.7:
                        self.move(api, (self.base_heading + 180) % 360, 40)
                    else:
                        api.set_speed(0); move_start_time = None
        finally:
            pygame.quit()

def main(toy_name=None, joystickID=0, playerID=1):
    pygame.init(); pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No joysticks found."); return
    joystick = pygame.joystick.Joystick(joystickID); joystick.init()
    sphero_color = Color(255, 0, 0)
    ctl = SpheroController(joystick, sphero_color, playerID)
    if toy_name is None: sys.exit("No toy name provided")
    ctl.discover_toy(toy_name)
    if ctl.toy: ctl.control_toy()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python script.py <toy_name> <joystickNumber 0-1> <player 1-5>")
        sys.exit(1)
    toy_name = sys.argv[1]; joystick = int(sys.argv[2]); playerid = int(sys.argv[3])
    print(f"Try to connect to: {toy_name} with number {joystick} for player {playerid}")
    main(toy_name, joystick, playerid)