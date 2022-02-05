import requests
import numpy as np
import time
import rawpy
from astropy.io import fits
from client import Client

TIMEOUT = 600
output = "output.fits"
url = "http://nova.astrometry.net/api/"

class UploadError(Exception):
    pass


def get_results(jobid):
    img = requests.get(f"http://nova.astrometry.net/api/jobs/{jobid}/info/").json()
    ra = img["calibration"]["ra"]
    dec = img["calibration"]["dec"]
    print(f"RA: {ra}, DEC: {dec}")

    return {"ra": img["calibration"]["ra"], "dec": img["calibration"]["dec"]}


def solve_image(img_filename: str, api_key: str, ra: float, dec: float, radius: float):
    ext = img_filename.partition(".")[2]  # Get file extension

    # Convert .CR2 to .fits if necessary
    if ext == "CR2":
        with rawpy.imread(img_filename) as image:
            image_array = image.postprocess()

        img = image_array[:, :, 1]
        newhdu = fits.PrimaryHDU(img)
        newhdu.writeto(output, overwrite=True)
        print("Image successfully converted to FITS")

    c = Client(apiurl=url)
    c.login(api_key)
    subid = None

    upload_kwargs = {"scale_units": "degwidth", "center_ra": ra, "center_dec": dec, "radius": radius}

    # Attempt to upload image twice
    for i in range(2):
        upres = c.upload(output, **upload_kwargs)
        if upres["status"] == "success":
            subid = upres["subid"]
            print(f"Image uploaded successfully\nSubmission ID: {subid}")
            break
        else:
            print("Image upload failed, trying again...")

    if subid is None:
        raise UploadError("Image failed to upload.")

    print("Awaiting job submission...")
    start = time.time()
    while True:
        if time.time() - start > TIMEOUT:
            raise TimeoutError

        jobid_list = requests.get(f"http://nova.astrometry.net/api/submissions/{subid}").json()["jobs"]
        if not jobid_list or not jobid_list[0]:
            time.sleep(1)
            continue

        jobid = jobid_list[0]
        status = requests.get(f"http://nova.astrometry.net/api/jobs/{jobid}").json()["status"]

        if status == "solving":
            time.sleep(1)
            continue

        if status == "success":
            print(f"Job completed in {round(time.time() - start, 1)} seconds")
            return get_results(jobid)

        else:
            print(f"Job failed in {round(time.time() - start, 1)} seconds")
            return None


