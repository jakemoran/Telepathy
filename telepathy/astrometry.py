import requests
import numpy as np
import time
import rawpy
import re
import subprocess
from astropy.io import fits
from client import Client

TIMEOUT = 600
url = "http://nova.astrometry.net/api/"

class UploadError(Exception):
    pass


def get_results(jobid):
    img = requests.get(f"http://nova.astrometry.net/api/jobs/{jobid}/info/").json()
    ra = img["calibration"]["ra"]
    dec = img["calibration"]["dec"]
    print(f"RA: {ra}, DEC: {dec}")

    return {"ra": img["calibration"]["ra"], "dec": img["calibration"]["dec"]}

def convert_to_fits(img_filename, output):
    with rawpy.imread(img_filename) as image:
        image_array = image.postprocess()

    img = image_array[:, :, 1]
    newhdu = fits.PrimaryHDU(img)
    newhdu.writeto(output, overwrite=True)
    print("Image successfully converted to FITS")


def solve_web(img_filename: str, api_key: str, ra: float, dec: float, radius: float):
    ext = img_filename.partition(".")[2]  # Get file extension

    # Convert .CR2 to .fits if necessary
    if ext == "CR2":
        convert_to_fits(img_filename, "output.fits")
        img_filename = "output.fits"

    c = Client(apiurl=url)
    c.login(api_key)
    subid = None

    upload_kwargs = {"scale_units": "degwidth", "center_ra": ra, "center_dec": dec, "radius": radius}

    # Attempt to upload image twice
    for i in range(2):
        upres = c.upload(img_filename, **upload_kwargs)
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

def solve_local(img_filename: str, ra: float, dec: float, radius: float = 10):
    name, ext = img_filename.split(".")  # Get file extension

    # Convert .CR2 to .fits if necessary
    if ext == "CR2":
        convert_to_fits(img_filename, f"{name}.fits")
        img_filename = f"{name}.fits"

    subprocess.run(f"solve-field --ra {ra} --dec {dec} --radius {radius} --no-remove-lines --uniformize 0 --no-plots "
                   "--crpix-center --match none --rdls none --new-fits none --corr none --index-xyls none --solved "
                   f"none {img_filename}", shell=True)
    subprocess.run(["rm", "*.axy"])
    result = read_wcs(f"{name}.wcs")
    subprocess.run(["rm", "*.wcs"])

    return result


def read_wcs(filepath: str):
    with open(filepath) as f:
        lines = f.read()

    lines = [line.strip() for line in re.split("=|        ", lines)]
    new_lines = []
    for line in lines:
        if "HISTORY" in line:
            break
        try:
            end = line.index("/")
            line = line[0:end].strip()
        except ValueError:
            line = line.strip()
        new_lines.append(line)
    new_lines = list(filter(None, new_lines))
    wcs = {}
    for i, j in zip(new_lines[0::2], new_lines[1::2]):
        wcs[i] = j

    return {"ra": float(wcs["CRVAL1"]), "dec": float(wcs["CRVAL2"])}
