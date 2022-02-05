import win32com.client as win
import time
import numpy as np

from astrometry import solve_image
from pydantic import BaseModel, Field, PrivateAttr
from typing import List, Any, Union, Optional
from astropy.io import fits
from pathlib import Path

TIMEOUT = 60


class Target(BaseModel):
    name: Optional[str] = None
    ra: float
    dec: float
    exposure_length: Optional[int] = None
    num_exposures: Optional[int] = None


def deg2hr(deg: float) -> float:
    """Convert degree to hour angle for RA"""
    return (deg / 360) * 24

def pointing_error(ra: float, dec: float, target: Target) -> tuple:
    """Determine pointing offset for a given target"""
    ra_error, dec_error = abs(target.ra - ra), abs(target.dec - dec)
    return (ra_error, dec_error)

def within_tolerance(error: tuple, tol: float) -> bool:
    """Determine if pointing error is within tolerance"""
    ra_error, dec_error = error
    return (ra_error <= tol and dec_error <= tol)


def status_check(func):
    """Run mount checks before slewing/syncing (possibly unnecessary)"""
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


class Session(BaseModel):
    apikey: str = Field(..., description="Authentication key for astrometry api")
    image_path: str = Field(..., description="Path to images")
    FOV_width: float = Field(..., description="Width in degrees of camera FOV")
    targets: List[Target] = Field(..., description="List of targets")

    connect_camera: bool = False
    connect_telescope: bool = False
    connect_focuser: bool = False
    connect_filter_wheel: bool = False

    camera: Any = None
    telescope: Any = None
    focuser: Any = None
    filter_wheel: Any = None

    _plate_solved: bool = PrivateAttr(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if self.connect_camera:
            self.camera = self.camera_init()
        if self.connect_telescope:
            self.telescope = self.telescope_init()


    def plate_solve(self, target: Optional[Target] = None, image_name: str = "output.fits",
                    exp_time: float = 0.5, gain: int = 9, tol: float = 1 / 60, attempts: int = 5):

        if target is None:
            try:
                target = self.targets[0]
            except IndexError:
                print("Target list empty, aborting...")
                return

        if self.telescope.AtPark:
            self.telescope.Unpark()

        for i in range(attempts):
            print("Slewing to target...")
            #self.slew_telescope(ra=target.ra, dec=target.dec)

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
            error = pointing_error(pointing_ra, pointing_dec, target)

            print(f"Pointing error - RA: {round(error[0], 4)}, DEC: {round(error[1], 4)}")
            print("Syncing...")

            #self.sync_telescope(ra=pointing_ra, dec=pointing_dec)
            if within_tolerance(error, tol):
                print(f"Plate solve succeeded in {i + 1} attempt" + ("s" if i > 0 else ""))
                self._plate_solved = True
                break
            elif i == attempts - 1:
                print("Attempt limit reached, aborting...")

    def take_image(self, duration: float, gain: int, output: Union[Path, str] = "output.fits"):
        if self.camera.Connected and self.camera.CameraState == 0:  # Camera state 0 implies camera is idle
            self.camera.Gain = gain
            self.camera.StartExposure(duration, True)
            time.sleep(duration)
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
        if not self.camera.ImageReady:
            print("No image to be saved")
            return

        print(f"Saving image to {output}")
        img = self.camera.ImageArray
        newhdu = fits.PrimaryHDU(np.array(img))
        newhdu.writeto(output, overwrite=True)

    def shoot_target(self, target: Target, terminate: bool = False):
        if not self._plate_solved:
            print("Warning: Pointing model not calibrated")
        prefix = target.name.lower().replace(" ", "_")

        self.slew_telescope(target.ra, target.dec)

        for i in range(target.num_exposures):
            self.take_image(duration=target.exposure_length, gain=9, output=f"{self.image_path}{prefix}{i}.fits")

        if terminate:
            self.end_session()

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
    def camera_init():
        cam = win.Dispatch("ASCOM.DSLR.Camera")
        cam.Connected = True
        if cam.Connected:
            print("Camera connected")
            return cam
        else:
            raise ConnectionError("Camera failed to connect")

    @staticmethod
    def telescope_init():
        tel = win.Dispatch("EQMOD.Telescope")
        tel.Connected = True
        if tel.Connected:
            print("Telescope connected: Waiting...")
            time.sleep(3)
            return tel
        else:
            raise ConnectionError("Telescope failed to connect")
