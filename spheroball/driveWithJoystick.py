#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pygame
import time
import sys
from spherov2 import scanner
from spherov2.types import Color
from spherov2.sphero_edu import SpheroEduAPI
from spherov2.commands.power import Power

# =================== INSTELLINGEN ===================
TILE_CM = 50.0          # 1 tegel = 50 cm
RUN_SPEED = 60          # traag (0..255) — verhoog later voor sneller
SPEED_CM_PER_S = 30.0   # cm/s bij RUN_SPEED op jullie vloer (tunen!)
SAFETY = 0.95           # iets < 1.0 zodat hij wat korter rijdt
HEADING_SETTLE = 0.30   # wacht na heading-wissel
DEADZONE = 0.15         # joystick deadzone
# ====================================================

buttons = {
    '1': 0, '2': 1, '3': 2, '4': 3,
    'L1': 4, 'R1': 5, 'L2': 6, 'R2': 7,
    'SELECT': 8, 'START': 9
}

class SpheroController:
    def __init__(self, joystick, color, ball_number):
        self.toy = None
        self.joystick = joystick
        self.color = color
        self.number = ball_number

        # GEEN auto-kalibratie of auto-heading
        self.base_heading = 0          # alleen wijzigen via R1/L1 (optioneel)
        self.previous_button = 0
        self.is_running = True

    # ---------- HULP ----------
    def _dz(self, v):  # deadzone
        return 0 if abs(v) < DEADZONE else v

    def _tiles_to_seconds(self, tiles: float) -> float:
        cm = tiles * TILE_CM
        return (cm / max(1e-6, SPEED_CM_PER_S)) * SAFETY

    # 4 tegels vooruit zonder heading te veranderen (géén set_heading!)
    def _drive_keep_heading(self, api, tiles: float, speed: int = RUN_SPEED):
        duration = self._tiles_to_seconds(tiles)
        api.set_speed(0)
        api.set_speed(speed)       # behoud huidige richting
        time.sleep(duration)
        api.set_speed(0)
        time.sleep(0.15)

    # Rijden met een RELATIEVE draai t.o.v. een referentieheading
    def _roll_rel(self, api, ref_heading: int, rel_deg: int, tiles: float, speed: int = RUN_SPEED):
        abs_heading = int((ref_heading + rel_deg) % 360)
        api.set_speed(0)
        api.set_heading(abs_heading)
        time.sleep(HEADING_SETTLE)
        api.roll(speed, abs_heading, self._tiles_to_seconds(tiles))
        api.set_speed(0)
        time.sleep(0.15)

    # Alleen draaien (geen rijden), rela­tief t.o.v. referentie
    def _turn_rel(self, api, ref_heading: int, rel_deg: int):
        abs_heading = int((ref_heading + rel_deg) % 360)
        api.set_speed(0)
        api.set_heading(abs_heading)
        time.sleep(HEADING_SETTLE)

    # ---------- TRAJECT ----------
    def run_course(self, api):
        """
        4 tegels vooruit (zonder heading te zetten) ->
        90° LINKS -> 4 tegels vooruit ->
        nog eens 90° LINKS (alleen draaien) -> stop.
        """
        print("\n--- AUTONOOM: 4→, 90° links, 4→, 90° links (eindoriëntatie) ---")
        t0 = time.time()

        # Referentie: neem de huidige heading alleen als LEES-waarde (niet zetten)
        start_heading = api.get_heading()

        # 1) 4 tegels vooruit — GEEN set_heading gebruikt
        self._drive_keep_heading(api, 4.0, RUN_SPEED)

        # 2) 90° LINKS (+90) en 4 tegels vooruit   <<< was -90 (rechts)
        self._roll_rel(api, start_heading, +90, 4.0, RUN_SPEED)

        # 3) Nogmaals 90° LINKS (alleen draaien)   <<< eindoriëntatie links
        self._turn_rel(api, start_heading, +180)  # +90 (stap 2) + +90 (nu) = +180 vanaf start

        api.set_speed(0)
        print(f"KLAAR — duur: {time.time()-t0:.2f} s\n")

    # ---------- VERBINDEN/BATTERIJ ----------
    def discover_toy(self, toy_name):
        try:
            self.toy = scanner.find_toy(toy_name=toy_name)
            if not self.toy:
                raise RuntimeError("Geen Sphero gevonden.")
            print(f"Sphero toy '{toy_name}' discovered.")
        except Exception as e:
            print(f"Error discovering toy: {e}")

    def connect_toy(self):
        if not self.toy:
            print("No toy discovered. Please run discover_toy() first.")
            return None
        try:
            return SpheroEduAPI(self.toy)
        except Exception as e:
            print(f"Error connecting to toy: {e}")
            return None

    def print_battery_level(self, api):
        try:
            v = Power.get_battery_voltage(self.toy)
            print(f"Battery: {v:.2f} V")
            if v > 4.1:   api.set_front_led(Color(0,255,0))
            elif v > 3.9: api.set_front_led(Color(255,255,0))
            elif v > 3.7: api.set_front_led(Color(255,100,0))
            else:         api.set_front_led(Color(255,0,0))
            if v < 3.5: sys.exit("Battery low — stop.")
        except Exception:
            pass

    # ---------- MAIN LOOP ----------
    def control_toy(self):
        with self.connect_toy() as api:
            last_batt = time.time()

            # GEEN auto-kalibratie en GEEN set_heading bij start!

            while self.is_running:
                pygame.event.pump()

                if time.time() - last_batt >= 30:
                    self.print_battery_level(api)
                    last_batt = time.time()

                # joystick lezen met deadzone
                X = self._dz(self.joystick.get_axis(0))
                Y = self._dz(self.joystick.get_axis(1))

                # KNOP 1: start traject
                btn1 = self.joystick.get_button(buttons['1'])
                if btn1 == 1 and self.previous_button == 0:
                    self.run_course(api)
                self.previous_button = btn1

                # R1/L1: (optioneel) basishoek veranderen in stappen van 45°
                if self.joystick.get_button(buttons['R1']) == 1:
                    self.base_heading = (self.base_heading + 45) % 360
                    api.set_speed(0); api.set_heading(self.base_heading)
                    time.sleep(0.25)
                if self.joystick.get_button(buttons['L1']) == 1:
                    self.base_heading = (self.base_heading - 45) % 360
                    api.set_speed(0); api.set_heading(self.base_heading)
                    time.sleep(0.25)

                # (optioneel) traag manueel rijden met Y
                if Y < -0.7:
                    api.set_speed(0); api.set_heading(self.base_heading)
                    api.roll(50, self.base_heading, 0.8)
                    api.set_speed(0)
                elif Y > 0.7:
                    back = (self.base_heading + 180) % 360
                    api.set_speed(0); api.set_heading(back)
                    api.roll(40, back, 0.8)
                    api.set_speed(0)
                else:
                    api.set_speed(0)

            api.set_speed(0)

def main(toy_name=None, joystickID=0, playerID=1):
    pygame.init(); pygame.joystick.init()
    if pygame.joystick.get_count() == 0:
        print("No joysticks found."); return
    joystick = pygame.joystick.Joystick(joystickID); joystick.init()

    sphero_color = Color(255, 0, 0)
    ctl = SpheroController(joystick, sphero_color, playerID)

    if toy_name is None:
        sys.exit("No toy name provided")

    ctl.discover_toy(toy_name)
    if ctl.toy:
        ctl.control_toy()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python script.py <toy_name> <joystickNumber 0-1> <player 1-5>")
        sys.exit(1)
    toy_name = sys.argv[1]
    joystick = int(sys.argv[2])
    playerid = int(sys.argv[3])
    print(f"Try to connect to: {toy_name} with number {joystick} for player {playerid}")
    main(toy_name, joystick, playerid)

