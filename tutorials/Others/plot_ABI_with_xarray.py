#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Thu Mar 24 10:59:46 2022

@author: ghiggi
"""
import requests
import cartopy
import cartopy.crs as ccrs
import xarray as xr
from io import BytesIO
import matplotlib.pyplot as plt
from goes_api import find_latest_files

###---------------------------------------------------------------------------.
#### Define protocol
base_dir = None

protocol = "gcs"
protocol = "s3"
fs_args = {}

###---------------------------------------------------------------------------.
#### Define satellite, sensor, product_level and product
satellite = "GOES-16"
sensor = "ABI"
product_level = "L1B"
product = "Rad"

###---------------------------------------------------------------------------.
#### Define sector and filtering options
sector = "F"
scan_modes = None   # select all scan modes (M3, M4, M6)
channels = None     # select all channels
channels = ["C01"]  # select channels subset
scene_abbr = None   
filter_parameters = {}
filter_parameters["scan_modes"] = scan_modes
filter_parameters["channels"] = channels
filter_parameters["scene_abbr"] = scene_abbr

#----------------------------------------------------------------------------.
#### Open file using in-memory buffering via https requests  
fpaths = find_latest_files(
    protocol=protocol,
    fs_args=fs_args,
    satellite=satellite,
    sensor=sensor,
    product_level=product_level,
    product=product,
    sector=sector,
    filter_parameters=filter_parameters,
    connection_type="https",
)
# - Select http url
fpath = list(fpaths.values())[0][0]
print(fpath)

# - Open the dataset 
resp = requests.get(fpath)
f_obj = BytesIO(resp.content)
ds = xr.open_dataset(f_obj)

# Dataset Name 
ds.title

# Radiance array 
arr = ds['Rad'].data

#----------------------------------------------------------------------------.
#### Retrieve GEOS projection x and y coordinates 
# - GEOS projection coordinates equals the scanning angle (in radians) 
#   multiplied by the satellite height
# - GEOS projection: (http://proj4.org/projections/geos.html)

# Projection informations
print(ds['goes_imager_projection'])

# Satellite height
sat_h = ds['goes_imager_projection'].perspective_point_height

# Satellite longitude
sat_lon = ds['goes_imager_projection'].longitude_of_projection_origin

# Satellite sweep
sat_sweep = ds['goes_imager_projection'].sweep_angle_axis

# Retrieve X and Y projection coordinates array 
X = ds['x'].data * sat_h
Y = ds['y'].data * sat_h

#----------------------------------------------------------------------------.
#### Plot with matplotlib and cartopy 
# - Define cartopy Geostationary projection 
crs_proj = ccrs.Geostationary(satellite_height=sat_h, 
                              central_longitude=sat_lon,
                              sweep_axis='x')

# - Create figure
fig, ax = plt.subplots(figsize=(10, 10), subplot_kw={'projection': crs_proj})
 
# - Plot radiance array
p = ax.pcolorfast(X, Y, arr, cmap='Spectral', zorder=0, vmin=10)

# - Add coastlines
ax.add_feature(cartopy.feature.COASTLINE, zorder=1, color='b', lw=1)

# - Add title
ax.set_title('GOES16', fontweight='bold', fontsize=12)

# - Add colorbar 
cbar = plt.colorbar(p, ax=ax, shrink=0.75)
cbar.set_label('Radiance',fontsize=12)
cbar.ax.tick_params(labelsize=10)

# - Set tight layout 
plt.tight_layout()

#----------------------------------------------------------------------------.
