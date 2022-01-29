import win32com.client as win
import time
import numpy as np

from astrometry import solve_image
from pydantic import BaseModel, Field
from typing import List, Any, Union, Optional
from astropy.io import fits
from pathlib import Path

TIMEOUT = 60


def deg2hr(deg: float):
    return (deg / 360) * 24


def status_check(func):
    def wrapper(*args, **kwargs):
        tel = args[0].telescope
        assert tel.CanPark
        assert tel.CanSlew
        assert not tel.Slewing
        time.sleep(1)
        func(*args, **kwargs)
        time.sleep(1)
        assert tel.CanSync
        assert tel.CanSetTracking
    return wrapper


class Target(BaseModel):
    name: Optional[str] = None
    ra: float
    dec: float
    exposure_length: Optional[int] = None
    num_exposures: Optional[int] = None


class Session(BaseModel):
    apikey: str = Field(..., description="Authentication key for astrometry api")
    image_path: str = Field(..., description="Path to images")
    FOV_width: float = Field(..., description="Width in degrees of camera FOV")
    targets: List[Target] = Field(..., description="List of targets")

    camera: Any = None
    telescope: Any = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.camera = self.connect_camera()
        self.telescope = self.connect_telescope()


    def plate_solve(self, target: Target, image_name: str = "output.fits",
                    exp_time: float = 0.5, gain: int = 9, tol: float = 1 / 60, attempts: int = 5):

        if self.telescope.AtPark:
            self.telescope.Unpark()

        for i in range(attempts):
            print("Slewing to target...")
            self.slew_telescope(ra=target.ra, dec=target.dec)

            print("Taking image...")
            self.take_image(duration=exp_time, gain=gain, output=image_name)
            solution = solve_image(
                img_filename=image_name,
                api_key=self.apikey,
                ra=target.ra,
                dec=target.dec,
                radius=self.FOV_width * 0.75
            )

            if solution is None:
                print("Plate solving failed, aborting...")
                break

            pointing_ra, pointing_dec = solution["ra"], solution["dec"]
            ra_error, dec_error = abs(target.ra - pointing_ra), abs(target.dec - pointing_dec)

            print(f"Pointing error - RA: {ra_error}, DEC: {dec_error}")
            print("Syncing...")

            self.sync_telescope(ra=pointing_ra, dec=pointing_dec)
            if ra_error <= tol and dec_error <= tol:
                print(f"Plate solve succeeded in {i + 1} attempt" + ("s" if i > 0 else ""))
                break
            elif i == attempts - 1:
                print("Attempt limit reached, aborting...")

    def take_image(self, duration: float, gain: int, output: Union[Path, str]):
        if self.camera.Connected and self.camera.CameraState == 0:  # Camera state 0 implies camera is idle
            self.camera.Gain = gain
            self.camera.StartExposure(duration, True)
            start = time.time()

            while True:
                if time.time() - start > TIMEOUT:
                    raise TimeoutError

                if self.camera.ImageReady:
                    self.save_image(output)
                    break
                time.sleep(1)
        else:
            raise ConnectionError("Process failed: Camera unavailable")

    def save_image(self, output: Union[Path, str]):
        print(f"Saving image to {output}")
        img = self.camera.ImageArray
        newhdu = fits.PrimaryHDU(np.array(img))
        newhdu.writeto(output, overwrite=True)

    @status_check
    def slew_telescope(self, ra: float, dec: float):
        """RA and Dec should both be in degrees"""
        ra = deg2hr(ra)
        if not self.telescope.Tracking:
            self.telescope.Tracking = True
        self.telescope.SlewToCoordinates(ra, dec)

    @status_check
    def sync_telescope(self, ra: float, dec: float):
        """RA and Dec should both be in degrees"""
        ra = deg2hr(ra)
        if not self.telescope.Tracking:
            self.telescope.Tracking = True
        self.telescope.SyncToCoordinates(ra, dec)

    @staticmethod
    def connect_camera():
        cam = win.Dispatch("ASCOM.DSLR.Camera")
        cam.Connected = True
        if cam.Connected:
            print("Camera connected")
            return cam
        else:
            raise ConnectionError("Camera failed to connect")

    @staticmethod
    def connect_telescope():
        tel = win.Dispatch("EQMOD.Telescope")
        tel.Connected = True
        if tel.Connected:
            print("Telescope connected: Waiting...")
            time.sleep(3)
            return tel
        else:
            raise ConnectionError("Telescope failed to connect")
