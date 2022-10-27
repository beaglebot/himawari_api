#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 Ghiggi Gionata, Léo Jacquat

# himawari_api is free software: you can redistribute it and/or modify it under the
# terms of the GNU General Public License as published by the Free Software
# Foundation, either version 3 of the License, or (at your option) any later
# version.
#
# himawari_api is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR
# A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# himawari_api. If not, see <http://www.gnu.org/licenses/>.

import os
import fsspec
import datetime
import numpy as np
import pandas as pd
from trollsift import Parser
from himawari_api.utils.time import _dt_to_year_month_day_hhmm

####--------------------------------------------------------------------------.
#### Alias
 
_satellites = {
    "himawari-8": ["H8", "H08", "HIMAWARI-8", "HIMAWARI8"],
    "himawari-9": ["H9", "H08", "HIMAWARI-9", "HIMAWARI9"],
}

_sectors = {
    "FLDK": ["FLDK", "FULL", "FULLDISK", "FULL DISK", "F"],
    "Japan": ["JAPAN", "JAPAN_AREA", "JAPAN AREA", "J"],                         
    "Target": ["TARGET", "TARGET_AREA", "TARGET AREA", "T"],
    "Landmark": ["LANDMARK", "M", "MESOSCALE"],
}


# - Channel informations : https://www.data.jma.go.jp/mscweb/en/himawari89/space_segment/spsg_ahi.html
_channels = {
    "B01": ["B01", "C01", "1", "01", "0.47", "0.46", "BLUE", "B"],
    "B02": ["B02", "C02", "2", "02", "0.51", "RED", "R"],
    "B03": ["B03", "C03", "3", "03", "0.64", "GREEN", "G"],                                 
    "B04": ["B04", "C04", "4", "04", "0.86", "CIRRUS"],
    "B05": ["B05", "C05", "5", "05", "1.6", "SNOW/ICE"],
    "B06": ["B06", "C06", "6", "06", "2.3", "CLOUD PARTICLE SIZE", "CPS"],
    "B07": ["B07", "C07", "7", "07", "3.9", "IR SHORTWAVE WINDOW", "IR SHORTWAVE"],
    "B08": ["B08", "C08", "8", "08", "6.2", "UPPER-LEVEL TROPOSPHERIC WATER VAPOUR",  "UPPER-LEVEL WATER VAPOUR"],
    "B09": ["B09", "C09", "9", "09", "6.9", "7.0", "MID-LEVEL TROPOSPHERIC WATER VAPOUR", "MID-LEVEL WATER VAPOUR"],
    "B10": ["B10", "C10", "10", "10", "7.3", "LOWER-LEVEL TROPOSPHERIC WATER VAPOUR", "LOWER-LEVEL WATER VAPOUR"],
    "B11": ["B11", "C11", "11", "11", "8.6", "CLOUD-TOP PHASE", "CTP"],
    "B12": ["B12", "C12", "12", "12", "9.6", "OZONE"],
    "B13": ["B13", "C13", "13", "10.4", "CLEAN IR LONGWAVE WINDOW", "CLEAN IR"],
    "B14": ["B14", "C14", "14", "11.2", "IR LONGWAVE WINDOW", "IR LONGWAVE"],
    "B15": ["B16","C15", "15", "12.3", "12.4", "DIRTY LONGWAVE WINDOW", "DIRTY IR"],
    "B16": ["B16","C16", "16", "13.3", "CO2 IR LONGWAVE", "CO2", "CO2 IR"],
}

PROTOCOLS = ["s3", "local", "file"]
BUCKET_PROTOCOLS = ["s3"]

####--------------------------------------------------------------------------.
#### Availability


def available_protocols():
    """Return a list of available cloud bucket protocols."""
    return BUCKET_PROTOCOLS


def available_satellites():
    """Return a list of available satellites."""
    return list(_satellites.keys())                                            


def available_sectors(product=None):
    """Return a list of available sectors.

    If `product` is specified, it returns the sectors available for such specific
    product.
    """
    from himawari_api.listing import AHI_L2_SECTOR_EXCEPTIONS

    sectors_keys = list(_sectors.keys())
    if product is None:
        return sectors_keys
    else:
        product = _check_product(product)
        specific_sectors = AHI_L2_SECTOR_EXCEPTIONS.get(product)
        if specific_sectors is None:
            return sectors_keys
        else:
            return specific_sectors


def available_product_levels():
    """Return a list of available product levels."""
    from himawari_api.listing import PRODUCTS
    product_levels = list(PRODUCTS["AHI"])        
    product_levels = np.unique(product_levels).tolist()
    return product_levels


def available_channels():
    """Return a list of available AHI channels."""
    channels = list(_channels.keys())
    return channels


def available_products(product_levels=None):
    """Return a list of available products.
    
    Specifying `product_levels` allows to retrieve only a specific subset of the list.
    """
    # Get product listing dictionary
    products_dict = get_dict_product_sensor(product_levels=product_levels)
    products = list(products_dict.keys())
    return products


def available_group_keys():
    """Return a list of available group_keys."""
    group_keys = [
        "product",
        "scene_abbr",  # ["R1","R2","R3","R4", "R5"]
        "channel",     # B**
        "sector",      # FLDK, Japan, Target, Landmark
        "platform_shortname",   
        "start_time",
        "end_time",
        "production_time",
        "spatial_res", 
        "segment_number",
        "segment_total"
    ]
    return group_keys


def available_connection_types():
    """Return a list of available connect_type to connect to cloud buckets."""
    return ["bucket", "https", "nc_bytes"]


####--------------------------------------------------------------------------.
#### Checks


def _check_protocol(protocol):
    """Check protocol validity."""
    if protocol is not None:
        if not isinstance(protocol, str):
            raise TypeError("`protocol` must be a string.")
        if protocol not in PROTOCOLS:
            raise ValueError(f"Valid `protocol` are {PROTOCOLS}.")
        if protocol == "local":
            protocol = "file"  # for fsspec LocalFS compatibility
    return protocol


def _check_base_dir(base_dir):
    """Check base_dir validity."""
    if base_dir is not None:
        if not isinstance(base_dir, str):
            raise TypeError("`base_dir` must be a string.")
        if not os.path.exists(base_dir):
            raise OSError(f"`base_dir` {base_dir} does not exist.")
        if not os.path.isdir(base_dir):
            raise OSError(f"`base_dir` {base_dir} is not a directory.")
    return base_dir


def _check_satellite(satellite):
    """Check satellite validity."""
    if not isinstance(satellite, str):
        raise TypeError("`satellite` must be a string.")
    # Retrieve satellite key accounting for possible aliases
    satellite_key = None
    for key, possible_values in _satellites.items():
        if satellite.upper() in possible_values:
            satellite_key = key
            break
    if satellite_key is None:
        valid_satellite_key = list(_satellites.keys())
        raise ValueError(f"Available satellite: {valid_satellite_key}")
    return satellite_key


def _check_sector(sector, product=None):                                      
    """Check sector validity."""
    if sector is None: 
        raise ValueError("'sector' must be specified.")

    if not isinstance(sector, str):
        raise TypeError("`sector` must be a string.")
    # Retrieve sector key accounting for possible aliases
    sector_key = None
    for key, possible_values in _sectors.items():
        if sector.upper() in possible_values:
            sector_key = key
            break
    # Raise error if provided unvalid sector key
    if sector_key is None:
        valid_sector_keys = list(_sectors.keys())
        raise ValueError(f"Available sectors: {valid_sector_keys}")
    # Check the sector is valid for a given product (if specified)
    valid_sectors = available_sectors(product=product)
    if product is not None:
        if sector_key not in valid_sectors:
            raise ValueError(
                f"Valid sectors for product {product} are {valid_sectors}."
            )
    return sector_key


def _check_product_level(product_level, product=None):
    """Check product_level validity."""
    if not isinstance(product_level, str):
        raise TypeError("`product_level` must be a string.")
    product_level = product_level.capitalize()
    if product_level not in ["L1b", "L2"]:
        raise ValueError("Available product levels are ['L1b', 'L2'].")
    if product is not None:
        if product not in get_dict_product_level_products()[product_level]:
            raise ValueError(
                f"`product_level` '{product_level}' does not include product '{product}'."
            )
    return product_level


def _check_product_levels(product_levels):
    """Check product_levels validity."""
    if isinstance(product_levels, str):
        product_levels = [product_levels]
    product_levels = [
        _check_product_level(product_level) for product_level in product_levels
    ]
    return product_levels

def _check_product(product, product_level=None):
    """Check product validity."""
    if not isinstance(product, str):
        raise TypeError("`product` must be a string.")
    valid_products = available_products(product_levels=product_level)
    # Retrieve product by accounting for possible aliases (upper/lower case)
    product_key = None
    for possible_values in valid_products:
        if possible_values.upper() == product.upper():
            product_key = possible_values
            break
    if product_key is None:
        if product_level is None:
            raise ValueError(f"Available products: {valid_products}")
        else:
            product_level = "" if product_level is None else product_level
            raise ValueError(f"Available {product_level} products: {valid_products}")
    return product_key


def _check_time(time):
    """Check time validity."""
    if not isinstance(time, (datetime.datetime, datetime.date, np.datetime64, str)):
        raise TypeError(
            "Specify time with datetime.datetime objects or a "
            "string of format 'YYYY-MM-DD hh:mm:ss'."
        )
    # If np.datetime, convert to datetime.datetime
    if isinstance(time, np.datetime64):
        time = time.astype('datetime64[s]').tolist()
    # If datetime.date, convert to datetime.datetime
    if not isinstance(time, (datetime.datetime, str)):
        time = datetime.datetime(time.year, time.month, time.day, 0, 0, 0)
    if isinstance(time, str):
        try:
            time = datetime.datetime.fromisoformat(time)
        except ValueError:
            raise ValueError("The time string must have format 'YYYY-MM-DD hh:mm:ss'")
    return time


def _check_start_end_time(start_time, end_time, res=None):
    """Check start_time and end_time validity."""
    # Format input
    start_time = _check_time(start_time)
    end_time = _check_time(end_time)
    
    # Set resolution to seconds
    start_time = start_time.replace(microsecond=0)
    end_time = end_time.replace(microsecond=0)
   
    # Round seconds to 00 or 30 
    # TODO @Leo in a separate function
    # If [0-15] --> 00 
    # If [15-45] --> 30 
    # If [45-59] --> 0 (and add 1 minute)
    
    # for time in [start_time, end_time]:      
    #     # if resolution is set to half-minute, replace time values
    #     if res == 0.5:       
    #         if time.second > 45:
    #             time.second = 0
    #             time.minute = time.minute+1
    #         elif (time.second < 45) and (time.second > 15):
    #             time.second = 30
    #         elif time.second < 15:
    #             time.second = 0
    #     else: 
    #         time.second = 0
    
    # Check start_time and end_time are chronological
    if start_time > end_time:
        raise ValueError("Provide start_time occuring before of end_time")
        
    # Check start_time and end_time are in the past
    if start_time > datetime.datetime.utcnow():
        raise ValueError("Provide a start_time occuring in the past.")
    if end_time > datetime.datetime.utcnow():
        raise ValueError("Provide a end_time occuring in the past.")
    return (start_time, end_time)


def _check_channel(channel):
    """Check channel validity."""
    if not isinstance(channel, str):
        raise TypeError("`channel` must be a string.")
    # Check channel follow standard name
    channel = channel.upper()
    if channel in list(_channels.keys()):
        return channel
    # Retrieve channel key accounting for possible aliases
    else:
        channel_key = None
        for key, possible_values in _channels.items():
            if channel.upper() in possible_values:
                channel_key = key
                break
        if channel_key is None:
            valid_channels_key = list(_channels.keys())
            raise ValueError(f"Available channels: {valid_channels_key}")
        return channel_key


def _check_channels(channels=None):
    """Check channels validity."""
    if channels is None:
        return channels
    if isinstance(channels, str):
        channels = [channels]
    channels = [_check_channel(channel) for channel in channels]
    return channels


def _check_scene_abbr(scene_abbr, sector=None):                 
    """Check AHI Japan, Target and Landmark sector scene_abbr validity."""
    if scene_abbr is None:
        return scene_abbr
    if sector is not None:
        if sector == "FLDK": 
            raise ValueError("`scene_abbr` must be specified only for Japan and Target sectors !")
    if not isinstance(scene_abbr, (str, list)):
        raise TypeError("Specify `scene_abbr` as string or list.")
    if isinstance(scene_abbr, str):
        scene_abbr = [scene_abbr]
    valid_scene_abbr = ["R1", "R2", "R3", "R4", "R5"]
    if not np.all(np.isin(scene_abbr, valid_scene_abbr)):
        raise ValueError(f"Valid `scene_abbr` values are {valid_scene_abbr}.")
    if sector is not None:
        if sector == "Japan": 
            valid_scene_abbr = ["R1", "R2"]
            if not np.all(np.isin(scene_abbr, valid_scene_abbr)):
                raise ValueError(f"Valid `scene_abbr` for Japan sector are {valid_scene_abbr}.")
        if sector == "Target":
            valid_scene_abbr = ["R3"]
            not np.all(np.isin(scene_abbr, valid_scene_abbr))
            raise ValueError(f"Valid `scene_abbr` for Target sector are {valid_scene_abbr}.")
        if sector == "Landmark":
            valid_scene_abbr = ["R4", "R5"]
            not np.all(np.isin(scene_abbr, valid_scene_abbr))
            raise ValueError(f"Valid `scene_abbr` for Landmark sector are {valid_scene_abbr}.")
            
    return scene_abbr


def _check_filter_parameters(filter_parameters, sector):          
    """Check filter parameters validity.

    It ensures that channels and scene_abbr are valid lists (or None).
    """
    if not isinstance(filter_parameters, dict):
        raise TypeError("filter_parameters must be a dictionary.")
    channels = filter_parameters.get("channels")
    scene_abbr = filter_parameters.get("scene_abbr")
    if channels:
        filter_parameters["channels"] = _check_channels(channels)
    if scene_abbr:
        filter_parameters["scene_abbr"] = _check_scene_abbr(scene_abbr, sector=sector)
    return filter_parameters


def _check_group_by_key(group_by_key):                                         # What's the use for this function ?
    """Check group_by_key validity."""
    if not isinstance(group_by_key, (str, type(None))):
        raise TypeError("`group_by_key`must be a string or None.")
    if group_by_key is not None:
        valid_group_by_key = available_group_keys()
        if group_by_key not in valid_group_by_key:
            raise ValueError(
                f"{group_by_key} is not a valid group_by_key. "
                f"Valid group_by_key are {valid_group_by_key}."
            )
    return group_by_key


def _check_connection_type(connection_type, protocol):
    """Check cloud bucket connection_type validity."""
    if not isinstance(connection_type, (str, type(None))):
        raise TypeError("`connection_type` must be a string (or None).")
    if protocol is None:
        connection_type = None
    if protocol in ["file", "local"]:
        connection_type = None  # set default
    if protocol in ["s3"]:
        # Set default connection type
        if connection_type is None:
            connection_type = "bucket"  # set default
        valid_connection_type = ["bucket", "https", "nc_bytes"]
        if connection_type not in valid_connection_type:
            raise ValueError(f"Valid `connection_type` are {valid_connection_type}.")
    return connection_type


def _check_interval_regularity(list_datetime):
    """Check regularity of a list of timesteps."""
    # TODO: raise info when missing between ... and ...
    if len(list_datetime) < 2:
        return None
    list_datetime = sorted(list_datetime)
    list_timedelta = np.diff(list_datetime)
    list_unique_timedelta = np.unique(list_timedelta)
    if len(list_unique_timedelta) != 1:
        raise ValueError("The time interval is not regular!")


####--------------------------------------------------------------------------.
#### Dictionary retrievals


def get_dict_info_products(product_levels=None):                  
    """Return a dictionary with sensors, product_level and product informations.

    The dictionary has structure {sensor: {product_level: [products]}}
    Specifying `sensors` and/or `product_levels` allows to retrieve only
    specific portions of the dictionary.
    """
    from himawari_api.listing import PRODUCTS
    sensor = "AHI"
    if product_levels is None:
        product_levels = available_product_levels()
    # Check product_levels
    product_levels = _check_product_levels(product_levels)
    # Subset by sensors
    sensor_dictionary = {sensor: PRODUCTS[sensor]}
    # Subset the product dictionary 
    listing_dict = {}
    for sensor, product_level_dict in sensor_dictionary.items():
        for product_level, products_dict in product_level_dict.items():
            if product_level in product_levels:
                if listing_dict.get(sensor) is None:
                    listing_dict[sensor] = {}
                listing_dict[sensor][product_level] = products_dict
    # Return filtered listing_dict
    return listing_dict


def get_dict_product_sensor(product_levels=None):
    """Return a dictionary with available product and corresponding sensors.

    The dictionary has structure {product: sensor}.
    Specifying `sensors` and/or `product_levels` allows to retrieve only a
    specific subset of the dictionary.
    """
    # Get product listing dictionary
    products_listing_dict = get_dict_info_products(product_levels=product_levels)
    # Retrieve dictionary
    products_sensor_dict = {}
    for sensor, product_level_dict in products_listing_dict.items():
        for product_level, products_dict in product_level_dict.items():
            for product in products_dict.keys():
                products_sensor_dict[product] = "AHI"
    return products_sensor_dict


def get_dict_sensor_products(sensors=None, product_levels=None):
    """Return a dictionary with available sensors and corresponding products.

    The dictionary has structure {sensor: [products]}.
    Specifying `sensors` and/or `product_levels` allows to retrieve only a
    specific subset of the dictionary.
    """
    products_sensor_dict = get_dict_product_sensor(
        sensors=sensors, product_levels=product_levels
    )
    sensor_product_dict = {}
    for k in set(products_sensor_dict.values()):
        sensor_product_dict[k] = []
    for product, sensor in products_sensor_dict.items():
        sensor_product_dict[sensor].append(product)
    return sensor_product_dict


def get_dict_product_product_level(sensors=None, product_levels=None):
    """Return a dictionary with available products and corresponding product_level.

    The dictionary has structure {product: product_level}.
    Specifying `sensors` and/or `product_levels` allows to retrieve only a
    specific subset of the dictionary.
    """
    # Get product listing dictionary
    products_listing_dict = get_dict_info_products(
        sensors=sensors, product_levels=product_levels
    )
    # Retrieve dictionary
    products_product_level_dict = {}
    for sensor, product_level_dict in products_listing_dict.items():
        for product_level, products_dict in product_level_dict.items():
            for product in products_dict.keys():
                products_product_level_dict[product] = product_level
    return products_product_level_dict


def get_dict_product_level_products(sensors=None, product_levels=None):
    """Return a dictionary with available product_levels and corresponding products.

    The dictionary has structure {product_level: [products]}.
    Specifying `sensors` and/or `product_levels` allows to retrieve only a
    specific subset of the dictionary.
    """
    products_product_level_dict = get_dict_product_product_level(
        sensors=sensors, product_levels=product_levels
    )
    product_level_product_dict = {}
    for k in set(products_product_level_dict.values()):
        product_level_product_dict[k] = []
    for product, sensor in products_product_level_dict.items():
        product_level_product_dict[sensor].append(product)
    return product_level_product_dict


####--------------------------------------------------------------------------.
#### Filesystems, buckets and directory structures
def get_filesystem(protocol, fs_args={}):
    """
    Define ffspec filesystem.

    protocol : str
       String specifying the cloud bucket storage from which to retrieve
       the data. It must be specified if not searching data on local storage.
       Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
       Dictionary specifying optional settings to initiate the fsspec.filesystem.
       The default is an empty dictionary. Anonymous connection is set by default.

    """
    if not isinstance(fs_args, dict):
        raise TypeError("fs_args must be a dictionary.")
    if protocol == "s3":
        # Set defaults
        # - Use the anonymous credentials to access public data
        _ = fs_args.setdefault("anon", True)  # TODO: or if is empty
        fs = fsspec.filesystem("s3", **fs_args)
        return fs
    elif protocol in ["local", "file"]:
        fs = fsspec.filesystem("file")
        return fs
    else:
        raise NotImplementedError(
            "Current available protocols are 's3', 'local'."
        )


def get_bucket(protocol, satellite):
    """
    Get the cloud bucket address for a specific satellite.

    Parameters
    ----------
    protocol : str
         String specifying the cloud bucket storage from which to retrieve
         the data. Use `himawari_api.available_protocols()` to retrieve available protocols.
    satellite : str
        The acronym of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    """

    # Dictionary of bucket and urls
    bucket_dict = {
        "s3": "s3://noaa-{}".format(satellite.replace("-", "")),                # Should be himawari8
    }
    return bucket_dict[protocol]

def _switch_to_https_fpath(fpath, protocol): 
    """
    Switch bucket address with https address.

    Parameters
    ----------
    fpath : str
        A single bucket filepaths.
    protocol : str
         String specifying the cloud bucket storage from which to retrieve
         the data. Use `himawari_api.available_protocols()` to retrieve available protocols.
    """
    satellite = infer_satellite_from_path(fpath)
    https_base_url_dict = {
        "s3": "https://noaa-{}.s3.amazonaws.com".format(satellite.replace("-", "")),
    }
    base_url = https_base_url_dict[protocol]
    fpath = os.path.join(base_url, fpath.split("/", 3)[3])  
    return fpath 
    

def _switch_to_https_fpaths(fpaths, protocol):
    """
    Switch bucket address with https address.

    Parameters
    ----------
    fpaths : list
        List of bucket filepaths.
    protocol : str
         String specifying the cloud bucket storage from which to retrieve
         the data. Use `himawari_api.available_protocols()` to retrieve available protocols.
    """
    fpaths = [_switch_to_https_fpath(fpath, protocol) for fpath in fpaths]
    return fpaths


def _get_bucket_prefix(protocol):
    """Get protocol prefix."""
    if protocol == "s3":
        prefix = "s3://"
    elif protocol == "file":
        prefix = ""
    else:
        raise NotImplementedError(
            "Current available protocols are 's3', 'local'."
        )
    return prefix


def _get_product_name(product_level, product, sector):
    """Get bucket directory name of a product."""
    sensor = "AHI"
    if product_level == "L2" and sector != "FLDK" :
        raise ValueError("L2 product level provides only FLDK sector.")
    # TODO: Landmark not available in AWS right now. Currently searches in the Target directory.
    if sector == "Landmark": 
        sector = "Target"   
    if product == "Rad":
        product_name = f"{sensor}-{product_level}-{sector}"
    elif product in ["CMSK", "CHGT","CPHS"]:
        product_name = f"{sensor}-{product_level}-{sector}-Clouds"
    elif product in ["RRQPE"]:    
        product_name = f"{sensor}-{product_level}-{sector}-RainfallRate"
    else: 
        raise ValueError(f"Retrieval not implemented for  product '{product}'.")
        
    return product_name
        

def _get_product_dir(satellite, product_level, product, sector, protocol=None, base_dir=None):
    """Get product (bucket) directory path."""
    if base_dir is None:
        bucket = get_bucket(protocol, satellite)
    else:
        bucket = os.path.join(base_dir, satellite.upper())
        if not os.path.exists(bucket):
            raise OSError(f"The directory {bucket} does not exist.")
    product_name = _get_product_name(product_level, product, sector)
    product_dir = os.path.join(bucket, product_name)
    return product_dir


def get_fname_glob_pattern(product_level): 
    if product_level == "L1b": 
        fname_pattern = "*.bz2*"
    else: # L2 
        fname_pattern == "*.nc*"
    return fname_pattern 
    

def infer_satellite_from_path(path): 
    """Infer the satellite from the file path."""
    himawari8_patterns = ['himawari8', 'himawari-8', 'H8', 'H08']
    himawari9_patterns = ['himawari9', 'himawari-9', 'H9', 'H09'] 
    if np.any([pattern in path for pattern in himawari8_patterns]):
        return 'himawari-8'
    if np.any([pattern in path for pattern in himawari9_patterns]):
        return 'himawari-9'
    else:
        raise ValueError("Unexpected HIMAWARI file path.")


def remove_bucket_address(fpath):
    """Remove the bucket acronym (i.e. s3://) from the file path."""
    fel = fpath.split("/")[3:]
    fpath = os.path.join(*fel)
    return fpath

####---------------------------------------------------------------------------.
#### Filtering


def _infer_product_level(fpath):
    """Infer product_level from filepath."""
    fname = os.path.basename(fpath)
    # Check if it is a L2 product 
    l2_products = ["HYDRO_RAIN_RATE", "RRQPE", "CLOUD_HEIGHT", "CHGT", "CLOUD_MASK", "CMSK", "CLOUD_PHASE", "CPHS"]
    bool_valid_product = [product in fname for product in l2_products]
    if np.any(bool_valid_product):
        product_level = "L2"
    # Otherwise check if it is a L1b Rad product  
    # - It could also check that "_B" is in fname  
    elif 'HS' in fname:
        product_level = 'L1b'
    else: 
        raise ValueError(f"`product_level` could not be inferred from {fname}.")
    # Return product 
    return product_level 
    

def _infer_product(fpath):
    '''Infer product from filepath.'''
    fname = os.path.basename(fpath)
    # Check if it is a L2 product 
    l2_products = ["HYDRO_RAIN_RATE", "RRQPE", "CLOUD_HEIGHT", "CHGT", "CLOUD_MASK", "CMSK", "CLOUD_PHASE", "CPHS"]
    bool_valid_product = [product in fname for product in l2_products]
    if np.any(bool_valid_product):
        product = l2_products[np.argwhere(bool_valid_product)[0][0]]
    # Otherwise check if it is a L1b Rad product  
    # - It could also check that "_B" is in fname  
    elif 'HS' in fname:
        product = 'Rad'
    else: 
        raise ValueError(f"`product` could not be inferred from {fname}.")
    # Return product 
    return product 


def _infer_satellite(fpath):
    """Infer satellite from filepath."""
    fname = os.path.basename(fpath)
    # GG SUGGESTION: if [h08, himawari8, himawari-8] in fpath.lower()
    himawari8_patterns = ['himawari8', 'himawari-8', 'H8', 'H08']
    himawari9_patterns = ['himawari9', 'himawari-9', 'H9', 'H09'] 
    
    if np.any([pattern in fpath for pattern in himawari8_patterns]):
        return 'himawari-8'
    if np.any([pattern in fpath for pattern in himawari9_patterns]):
        return 'himawari-9'
    else: 
        raise ValueError(f"`satellite` could not be inferred from {fname}.")


def _separate_sector_observation_number(sector_observation_number):
    """Return (sector, scene_abbr, observation_number) from <sector><observation_number> string."""
    # See Table 4 in https://www.data.jma.go.jp/mscweb/en/himawari89/space_segment/hsd_sample/HS_D_users_guide_en_v12.pdf
    # - FLDK
    # - JP[01-04]  # 2.5 min ...  (4 times in 10 min)    # Japan (R1 and R2)
    # - R[301-304] # 2.5 min      (4 times in 10 min)    # Target Area  (R3)
    # - R[401-420] # 30 secs      (20 times in 10 min)   # LandMark Area (R4)
    # - R[501-520] # 30 secs      (20 times in 10 min)   # LandMark Area (R5)
    if "FLDK" in sector_observation_number:
        sector = "FLDK"
        scene_abbr = "F"
        observation_number = None
    elif "JP" in sector_observation_number:
        sector = "JP"
        scene_abbr = ["R1","R2"]
        observation_number = int(sector_observation_number[-2:])
    elif "R" in sector_observation_number:  
        region_index = int(sector_observation_number[1])
        if region_index == 3: 
            sector = "Target" 
            scene_abbr = "R3"
        elif region_index == 4: 
            sector = "Landmark"  
            scene_abbr = "R4"
        else: 
            sector = "Landmark"  
            scene_abbr = "R5"
        observation_number = int(sector_observation_number[2:])
    else:
        raise NotImplementedError("Adapt the file patterns.")
    return sector, scene_abbr, observation_number


def _get_info_from_filename(fname):
    """Retrieve file information dictionary from filename."""
    from himawari_api.listing import GLOB_FNAME_PATTERN
    
    # Infer sensor and product_level
    sensor = "AHI"
    product_level = _infer_product_level(fname)
    product = _infer_product(fname)
    
    # Retrieve file pattern
    fpattern = GLOB_FNAME_PATTERN[sensor][product_level][product]       
    
    # Retrieve information from filename 
    p = Parser(fpattern)
    info_dict = p.parse(fname)
    
    info_dict["sensor"] = sensor
    info_dict["product_level"] = product_level
        
    # Round start_time and end_time to minute resolution
    for time in ["start_time", "end_time", "production_time", "creation_time"]:
        try:
            info_dict[time] = info_dict[time].replace(microsecond=0) # Removed second=0
        except:
            None
    
    # Parse sector_observation_number in L1b Rad files
    # - FLDK
    # - JP[01-04]  # 2.5 min ...  (4 times in 10 min)    # Japan (R1 and R2)
    # - R[301-304] # 2.5 min      (4 times in 10 min)    # Target Area   (R3)
    # - R[401-420] # 30 secs      (20 times in 10 min)   # LandMark Area (R4)
    # - R[501-520] # 30 secs      (20 times in 10 min)   # LandMark Area (R5)
    sector_observation_number = info_dict.get("sector_observation_number", None) 
    if sector_observation_number is not None: 
        sector, scene_abbr, observation_number = _separate_sector_observation_number(sector_observation_number)
        info_dict["sector"] = sector 
        info_dict["scene_abbr"] = scene_abbr             
        if sector == "Japan" or (sector == "Target" and scene_abbr == "R3"): 
            start_time = info_dict["start_time"]
            start_time = start_time + (observation_number-1)*datetime.timedelta(minutes=2, seconds=30)
            end_time = start_time + (observation_number)*datetime.timedelta(minutes=2, seconds=30)
            info_dict["start_time"] = start_time
            info_dict["end_time"] = end_time
        if sector == "Landmark" and scene_abbr in ["R4", "R5"]:
            start_time = info_dict["start_time"]
            start_time = start_time + (observation_number-1)*datetime.timedelta(seconds=30)
            end_time = start_time + (observation_number)*datetime.timedelta(seconds=30)
            info_dict["start_time"] = start_time
            info_dict["end_time"] = end_time
            
    # Retrieve end_time if not available in the file name 
    # --> L2 before the change in 2021, and L1b Rad for FLDK
    end_time = info_dict.get('end_time', None)
    if end_time is None: 
        end_time = info_dict['start_time'] + datetime.timedelta(minutes=10)
        info_dict["end_time"] = end_time
        
    # Retrieve sector if not available (i.e in L2)
    sector = info_dict.get('sector', None)
    if sector is None: 
        sector = "FLDK" # must be a L2 Product (the fname does not contain sector info).
        info_dict["sector"] = sector
        
    # Special treatment to homogenize L2 product names of CLOUDS AND RRQPE 
    if info_dict['product_level'] == "L2":
        product = info_dict['product']
        if product in ["CLOUD_MASK", "CMSK"]:
            product = "CMSK"
        elif product in ["CPHS", "CLOUD_PHASE"]: 
            product = "CPHS"
        elif product in ["CHGT", "CLOUD_HEIGHT"]: 
            product = "CHGT"
        elif product in ["RRQPE", "HYDRO_RAIN_RATE"]: 
            product = "RRQPE"
        else: 
            raise NotImplementedError()
    info_dict["product"] = product
    
    # Derive satellite name from platform_shortname if available 
    # - {platform_fullname} = "Himawari8", "Himawari9"
    # - {platform_shortname} = "h08", "H08", "h09", "H09"
    platform_shortname = info_dict.get("platform_shortname", None) 
    platform_fullname = info_dict.get("platform_fullname", None) 
    if platform_shortname is not None: 
        if 'H08' == platform_shortname.upper():
            satellite = 'HIMAWARI-8'
        elif 'H09' == platform_shortname.upper():
            satellite = 'HIMAWARI-9'
        else:
            raise ValueError(f"Processing of satellite {platform_shortname} not yet implemented.")
    elif platform_fullname is not None: 
        if 'HIMAWARI8' == platform_fullname.upper():
            satellite = 'HIMAWARI-8'
        elif 'HIMAWARI9' == platform_fullname.upper():
            satellite = 'HIMAWARI-9'
        else:
            raise ValueError(f"Processing of satellite {platform_fullname} not yet implemented.")        
    else: 
        raise ValueError("Satellite name not derivable from file name.") 
    info_dict["satellite"] =  satellite  
        
    # Return info dictionary
    return info_dict


def _get_info_from_filepath(fpath):
    """Retrieve file information dictionary from filepath."""
    if not isinstance(fpath, str):
        raise TypeError("'fpath' must be a string.")
    fname = os.path.basename(fpath)
    return _get_info_from_filename(fname)


def _get_key_from_filepaths(fpaths, key):
    """Extract specific key information from a list of filepaths."""
    if isinstance(fpaths, str):
        fpaths = [fpaths]
    return [
        _get_info_from_filepath(fpath)[key] for fpath in fpaths
    ]


def get_key_from_filepaths(fpaths, key):
    """Extract specific key information from a list of filepaths."""
    if isinstance(fpaths, dict):
        fpaths = {k: _get_key_from_filepaths(v, key=key) for k, v in fpaths.items()}
    else:
        fpaths = _get_key_from_filepaths(fpaths, key=key)
    return fpaths 

def _filter_file(
    fpath,
    product_level,
    start_time=None,
    end_time=None,
    channels=None,
    scene_abbr=None,
):
    """Utility function to filter a filepath based on optional filter_parameters."""
    # scene_abbr and channels must be list, start_time and end_time a datetime object
    # TODO: Currently no way to filter R1 and R2 (I think inside a single bz2 file.)
    # TODO: Currently R4 and R5 are not on AWS 

    # Get info from filepath
    info_dict = _get_info_from_filepath(fpath)

    # Filter by channels
    if channels is not None:
        file_channel = info_dict.get("channel")
        if file_channel is not None:
            if file_channel not in channels:
                return None

    # Filter by scene_abbr
    if scene_abbr is not None:
        file_scene_abbr = info_dict.get("scene_abbr")
        if file_scene_abbr is not None:
            if file_scene_abbr not in scene_abbr:
                return None
    
    # Filter by start_time
    if start_time is not None:
        # If the file ends before start_time, do not select
        file_end_time = info_dict.get("end_time")
        if file_end_time < start_time: 
            return None
        # This would exclude a file with start_time within the file
        # if file_start_time < start_time:
        #     return None

    # Filter by end_time
    if end_time is not None:
        file_start_time = info_dict.get("start_time")
        # If the file starts after end_time, do not select
        if file_start_time > end_time:
            return None
        # This would exclude a file with end_time within the file
        # if file_end_time > end_time:
        #     return None
    return fpath


def _filter_files(
    fpaths,
    product_level,
    start_time=None,
    end_time=None,
    channels=None,
    scene_abbr=None,
):
    """Utility function to select filepaths matching optional filter_parameters."""
    if isinstance(fpaths, str):
        fpaths = [fpaths]
    fpaths = [
        _filter_file(
            fpath,
            product_level,
            start_time=start_time,
            end_time=end_time,
            channels=channels,
            scene_abbr=scene_abbr,
        )
        for fpath in fpaths
    ]
    fpaths = [fpath for fpath in fpaths if fpath is not None]
    return fpaths


def filter_files(
    fpaths,
    product_level,
    start_time=None,
    end_time=None,
    scene_abbr=None,
    channels=None,
):
    """
    Filter files by optional parameters.

    The optional parameters can also be defined within a `filter_parameters`
    dictionary which is then passed to `find_files` or `download_files` functions.

    Parameters
    ----------
    fpaths : list
        List of filepaths.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    start_time : datetime.datetime, optional
        Time defining interval start.
        The default is None (no filtering by start_time).
    end_time : datetime.datetime, optional
        Time defining interval end.
        The default is None (no filtering by end_time).
    scene_abbr : str, optional
        String specifying selection of Japan, Target, or Landmark scan region.
        Either R1 or R2 for sector Japan, R3 for Target, R4 or R5 for Landmark.
        The default is None (no filtering by scan region).
    channels : list, optional
        List of AHI channels to select.
        See `himawari_api.available_channels()` for available AHI channels.
        The default is None (no filtering by channels).

    """
    product_level = _check_product_level(product_level, product=None)
    channels = _check_channels(channels)
    scene_abbr = _check_scene_abbr(scene_abbr)
    start_time, end_time = _check_start_end_time(start_time, end_time)
    fpaths = _filter_files(
        fpaths=fpaths,
        product_level=product_level,
        start_time=start_time,
        end_time=end_time,
        channels=channels,
        scene_abbr=scene_abbr,
    )
    return fpaths


####---------------------------------------------------------------------------.
#### Search files
def _get_acquisition_max_timedelta(sector):
    """Get reasonable timedelta based on AHI sector to find previous/next acquisition."""
    if sector == "Target":
       dt = datetime.timedelta(minutes=2, seconds=30)     
    elif sector == "Japan":
        dt = datetime.timedelta(minutes=2, seconds=30)    
    elif sector == "FLDK":
        dt = datetime.timedelta(minutes=10)   
    elif sector == "Landmark": 
        dt = datetime.timedelta(seconds=30)    
    else:
        raise ValueError("Unknown sector.")
    return dt




def _group_fpaths_by_key(fpaths, product_level=None, key="start_time"):
    """Utils function to group filepaths by key contained into filename.""" 
    # - Retrieve key sorting index 
    list_key_values = [_get_info_from_filepath(fpath)[key] for fpath in fpaths]
    idx_key_sorting = np.array(list_key_values).argsort()
    # - Sort fpaths and key_values by key values
    fpaths = np.array(fpaths)[idx_key_sorting]
    list_key_values = np.array(list_key_values)[idx_key_sorting]
    # - Retrieve first occurence of new key value
    unique_key_values, cut_idx = np.unique(list_key_values, return_index=True)
    # - Split by key value
    fpaths_grouped = np.split(fpaths, cut_idx)[1:]
    # - Convert array of fpaths into list of fpaths 
    fpaths_grouped = [arr.tolist() for arr in fpaths_grouped]
    # - Create (key: files) dictionary
    fpaths_dict = dict(zip(unique_key_values, fpaths_grouped))
    return fpaths_dict


def group_files(fpaths, key="start_time"):
    """
    Group filepaths by key contained into filenames.

    Parameters
    ----------
    fpaths : list
        List of filepaths.
    key : str
        Key by which to group the list of filepaths.
        The default key is "start_time".
        See `himawari_api.available_group_keys()` for available grouping keys.

    Returns
    -------
    fpaths_dict : dict
        Dictionary with structure {<key>: list_fpaths_with_<key>}.

    """
    if isinstance(fpaths, dict): 
        raise TypeError("It's not possible to group a dictionary ! Pass a list of filepaths instead.")
    key = _check_group_by_key(key)
    fpaths_dict = _group_fpaths_by_key(fpaths=fpaths, key=key)
    return fpaths_dict


def find_files(
    satellite,
    product_level,
    product,
    start_time,
    end_time,
    sector=None, 
    filter_parameters={},
    group_by_key=None,
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    verbose=False,
):
    """
    Retrieve files from local or cloud bucket storage.

    If you are querying data from sector 'Japan', 'Target' or 'Landmark', you might be
      interested to specify in the filter_parameters dictionary the
      key `scene_abbr` with values "R1", "R2" (for Japan), "R3" (for Target") or  
     "R4" and "R5" (for Landmark).
      
    Parameters
    ----------
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    start_time : datetime.datetime
        The start (inclusive) time of the interval period for retrieving the filepaths.
    end_time : datetime.datetime
        The end (exclusive) time of the interval period for retrieving the filepaths.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters : dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    group_by_key : str, optional
        Key by which to group the list of filepaths
        See `himawari_api.available_group_keys()` for available grouping keys.
        If a key is provided, the function returns a dictionary with grouped filepaths.
        By default, no key is specified and the function returns a list of filepaths.
    connection_type : str, optional
        The type of connection to a cloud bucket.
        This argument applies only if working with cloud buckets (base_dir is None).
        See `himawari_api.available_connection_types` for implemented solutions.
    verbose : bool, optional
        If True, it print some information concerning the file search.
        The default is False.

    """

    # Check inputs
    if protocol is None and base_dir is None:
        raise ValueError("Specify 1 between `base_dir` and `protocol`")
    if base_dir is not None:
        if protocol is not None:
            if protocol not in ["file", "local"]:
                raise ValueError("If base_dir is specified, protocol must be None.")
        else:
            protocol = "file"
            fs_args = {}
    # Format inputs
    protocol = _check_protocol(protocol)
    base_dir = _check_base_dir(base_dir)
    connection_type = _check_connection_type(connection_type, protocol)
    satellite = _check_satellite(satellite)
    product_level = _check_product_level(product_level, product=None)
    product = _check_product(product, product_level=product_level)
    sector = _check_sector(sector, product=product)  
    start_time, end_time = _check_start_end_time(start_time, end_time) 
    filter_parameters = _check_filter_parameters(filter_parameters, sector=sector)
    group_by_key = _check_group_by_key(group_by_key)

    # Add start_time and end_time to filter_parameters
    filter_parameters = filter_parameters.copy()
    filter_parameters["start_time"] = start_time
    filter_parameters["end_time"] = end_time

    # Get filesystem
    fs = get_filesystem(protocol=protocol, fs_args=fs_args)

    bucket_prefix = _get_bucket_prefix(protocol)

    # Get product dir
    product_dir = _get_product_dir(
        protocol=protocol,
        base_dir=base_dir,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
    )

    # Define time directories 
    # <YYYY>/<MM>/<DD>/<HH00, HH10, HH20,...>)
    list_hourly_times = pd.date_range(start_time, end_time, freq="10min")
    # list_hourly_times = pd.date_range(start_time, end_time+datetime.timedelta(minutes=10), freq="10min")
    list_time_dir_tree = ["/".join(_dt_to_year_month_day_hhmm(dt)) for dt in list_hourly_times]

    # Define glob patterns 
    fname_glob_pattern = get_fname_glob_pattern(product_level=product_level)
    list_glob_pattern = [os.path.join(product_dir, time_dir_tree, fname_glob_pattern) for time_dir_tree in list_time_dir_tree]
    n_directories = len(list_glob_pattern)
    if verbose:
        print(f"Searching files across {n_directories} directories.")

    # Loop over each directory:
    # - TODO in parallel 
    list_fpaths = []
    # glob_pattern = list_glob_pattern[0]
    for glob_pattern in list_glob_pattern:
        # Retrieve list of files
        fpaths = fs.glob(glob_pattern)
        # Add bucket prefix
        fpaths = [bucket_prefix + fpath for fpath in fpaths]
        # Filter files if necessary
        if len(filter_parameters) >= 1:
            fpaths = _filter_files(fpaths, product_level, **filter_parameters)  
        list_fpaths += fpaths

    fpaths = list_fpaths

    # Group fpaths by key
    if group_by_key:
        fpaths = _group_fpaths_by_key(fpaths, product_level, key=group_by_key)  
        
    # Parse fpaths for connection type
    fpaths = _set_connection_type(
        fpaths, satellite=satellite, protocol=protocol, connection_type=connection_type
    )
    # Return fpaths
    return fpaths


def find_closest_start_time(
    time,
    satellite,
    product_level,
    product,
    sector=None, 
    base_dir=None,
    protocol=None,
    fs_args={},
    filter_parameters={},
):
    """
    Retrieve files start_time closest to the specified time.

    Parameters
    ----------
    time : datetime.datetime
        The time for which you desire to know the closest file start_time.
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters: dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    """
    # Set time precision to minutes
    time = _check_time(time)
    time = time.replace(microsecond=0, second=0)
    # Retrieve timedelta conditioned to sector (for AHI)
    timedelta = _get_acquisition_max_timedelta(sector)
    # Define start_time and end_time
    start_time = time - timedelta
    end_time = time + timedelta
    # Retrieve files
    fpath_dict = find_files(
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        start_time=start_time,
        end_time=end_time,
        filter_parameters=filter_parameters,
        group_by_key="start_time",
        verbose=False,
    )
    # Select start_time closest to time
    list_datetime = sorted(list(fpath_dict.keys()))
    if len(list_datetime) == 0:
        dt_str = int(timedelta.seconds / 60)
        raise ValueError(
            f"No data available in previous and next {dt_str} minutes around {time}."
        )
    idx_closest = np.argmin(np.abs(np.array(list_datetime) - time))
    datetime_closest = list_datetime[idx_closest]
    return datetime_closest


def find_latest_start_time(
    satellite,
    product_level,
    product,
    sector=None, 
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    filter_parameters={},
    look_ahead_minutes=30,
):
    """
    Retrieve the latest file start_time available.

    Parameters
    ----------
    look_ahead_minutes: int, optional
        Number of minutes before actual time to search for latest data.
        THe default is 30 minutes.
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters: dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    """
    # Search in the past N hour of data
    start_time = datetime.datetime.utcnow() - datetime.timedelta(
        minutes=look_ahead_minutes
    )
    end_time = datetime.datetime.utcnow()
    fpath_dict = find_files(
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        start_time=start_time,
        end_time=end_time,
        filter_parameters=filter_parameters,
        group_by_key="start_time",
        connection_type=connection_type,
        verbose=False,
    )
    # Find the latest time available
    if len(fpath_dict) == 0: 
        raise ValueError("No data found. Maybe try to increase `look_ahead_minutes`.")
    list_datetime = list(fpath_dict.keys())
    idx_latest = np.argmax(np.array(list_datetime))
    datetime_latest = list_datetime[idx_latest]
    return datetime_latest


def find_closest_files(
    time,
    satellite,
    product_level,
    product,
    sector=None, 
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    filter_parameters={},
):
    """
    Retrieve files closest to the specified time.

    If you are querying mesoscale domain data (sector=M), you might be
      interested to specify in the filter_parameters dictionary the
      key `scene_abbr` with values "M1" or "M2".

    Parameters
    ----------
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    time : datetime.datetime
        The time for which you desire to retrieve the files with closest start_time.
    filter_parameters : dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    connection_type : str, optional
        The type of connection to a cloud bucket.
        This argument applies only if working with cloud buckets (base_dir is None).
        See `himawari_api.available_connection_types` for implemented solutions.

    """
    # Set time precision to minutes
    time = _check_time(time)
    time = time.replace(microsecond=0, second=0)
    # Retrieve timedelta conditioned to sector type
    timedelta = _get_acquisition_max_timedelta(sector)
    # Define start_time and end_time
    start_time = time - timedelta
    end_time = time + timedelta
    # Retrieve files
    fpath_dict = find_files(
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        start_time=start_time,
        end_time=end_time,
        filter_parameters=filter_parameters,
        group_by_key="start_time",
        verbose=False,
    )
    # Select start_time closest to time
    list_datetime = sorted(list(fpath_dict.keys()))
    if len(list_datetime) == 0:
        dt_str = int(timedelta.seconds / 60)
        raise ValueError(
            f"No data available in previous and next {dt_str} minutes around {time}."
        )
    idx_closest = np.argmin(np.abs(np.array(list_datetime) - time))
    datetime_closest = list_datetime[idx_closest]
    return fpath_dict[datetime_closest]


def find_latest_files(
    satellite,
    product_level,
    product,
    sector=None, 
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    filter_parameters={},
    N = 1, 
    check_consistency=True, 
    look_ahead_minutes=30,
):
    """
    Retrieve latest available files.

    If you are querying mesoscale domain data (sector=M), you might be
      interested to specify in the filter_parameters dictionary the
      key `scene_abbr` with values "M1" or "M2".

    Parameters
    ----------
    look_ahead_minutes: int, optional
        Number of minutes before actual time to search for latest data.
        The default is 30 minutes.
    N : int
        The number of last timesteps for which to download the files.
        The default is 1.
    check_consistency : bool, optional
        Check for consistency of the returned files. The default is True.
        It check that:
         - the regularity of the previous timesteps, with no missing timesteps;
         - the regularity of the scan mode, i.e. not switching from M3 to M6,
         - if sector == M, the mesoscale domains are not changing within the considered period.
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters : dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    connection_type : str, optional
        The type of connection to a cloud bucket.
        This argument applies only if working with cloud buckets (base_dir is None).
        See `himawari_api.available_connection_types` for implemented solutions.

    """
    # Get closest time
    latest_time = find_latest_start_time(
        look_ahead_minutes=look_ahead_minutes, 
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        filter_parameters=filter_parameters,
    )
    
    fpath_dict = find_previous_files(
        N = N, 
        check_consistency=check_consistency,
        start_time=latest_time,
        include_start_time=True, 
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        filter_parameters=filter_parameters,
        connection_type=connection_type,
    )
    return fpath_dict


def find_previous_files(
    start_time,
    N,
    satellite,
    product_level,
    product,
    sector=None, 
    filter_parameters={},
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    include_start_time=False,
    check_consistency=True,
):
    """
    Find files for N timesteps previous to start_time.

    Parameters
    ----------
    start_time : datetime
        The start_time from which to search for previous files.
        The start_time should correspond exactly to file start_time if check_consistency=True
    N : int
        The number of previous timesteps for which to retrieve the files.
    include_start_time: bool, optional
        Wheter to include (and count) start_time in the N returned timesteps.
        The default is False.
    check_consistency : bool, optional
        Check for consistency of the returned files. The default is True.
        It check that:
         - start_time correspond exactly to the start_time of the files;
         - the regularity of the previous timesteps, with no missing timesteps;
         - the regularity of the scan mode, i.e. not switching from M3 to M6,
         - if sector == M, the mesoscale domains are not changing within the considered period.
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters : dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    connection_type : str, optional
        The type of connection to a cloud bucket.
        This argument applies only if working with cloud buckets (base_dir is None).
        See `himawari_api.available_connection_types` for implemented solutions.

    Returns
    -------
    fpath_dict : dict
        Dictionary with structure {<datetime>: [fpaths]}

    """
    sector = _check_sector(sector)
    product_level = _check_product_level(product_level)
    # Set time precision to minutes
    start_time = _check_time(start_time)
    start_time = start_time.replace(microsecond=0, second=0)
    # Get closest time and check is as start_time (otherwise warning)
    closest_time = find_closest_start_time(
        time=start_time,
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        filter_parameters=filter_parameters,
    )
    # Check start_time is the precise start_time of the file
    if check_consistency and closest_time != start_time:
        raise ValueError(
            f"start_time='{start_time}' is not an actual start_time. "
            f"The closest start_time is '{closest_time}'"
        )
    # Retrieve timedelta conditioned to sector type
    timedelta = _get_acquisition_max_timedelta(sector)
    # Define start_time and end_time
    start_time = closest_time - timedelta * (N+1) # +1 for when include_start_time=False
    end_time = closest_time
    # Retrieve files
    fpath_dict = find_files(
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        start_time=start_time,
        end_time=end_time,
        filter_parameters=filter_parameters,
        group_by_key="start_time",
        connection_type=connection_type,
        verbose=False,
    )
    # List previous datetime
    list_datetime = sorted(list(fpath_dict.keys()))
    # Remove start_time if include_start_time=False
    if not include_start_time:
        list_datetime.remove(closest_time)
    list_datetime = sorted(list_datetime)
    # Check data availability
    if len(list_datetime) == 0:
        raise ValueError(f"No data available between {start_time} and {end_time}.")
    if len(list_datetime) < N:
        raise ValueError(
            f"No {N} timesteps available between {start_time} and {end_time}."
        )
    # Select N most recent start_time
    list_datetime = list_datetime[-N:]
    # Select files for N most recent start_time
    fpath_dict = {tt: fpath_dict[tt] for tt in list_datetime}
    # ----------------------------------------------------------
    # Perform consistency checks
    if check_consistency:
        # Check for interval regularity
        if not include_start_time: 
            list_datetime = list_datetime + [closest_time]
        _check_interval_regularity(list_datetime)

    # ----------------------------------------------------------
    # Return files dictionary
    return fpath_dict


def find_next_files(
    start_time,
    N,
    satellite,
    product_level,
    product,
    sector=None, 
    filter_parameters={},
    connection_type=None,
    base_dir=None,
    protocol=None,
    fs_args={},
    include_start_time=False,
    check_consistency=True,
):
    """
    Find files for N timesteps after start_time.

    Parameters
    ----------
    start_time : datetime
        The start_time from which search for next files.
        The start_time should correspond exactly to file start_time if check_consistency=True
    N : int
        The number of next timesteps for which to retrieve the files.
    include_start_time: bool, optional
        Wheter to include (and count) start_time in the N returned timesteps.
        The default is False.
    check_consistency : bool, optional
        Check for consistency of the returned files. The default is True.
        It check that:
         - start_time correspond exactly to the start_time of the files;
         - the regularity of the previous timesteps, with no missing timesteps;
         - the regularity of the scan mode, i.e. not switching from M3 to M6,
         - if sector == M, the mesoscale domains are not changing within the considered period.
    base_dir : str
        Base directory path where the <HIMAWARI-**> satellite is located.
        This argument must be specified only if searching files on local storage.
        If it is specified, protocol and fs_args arguments must not be specified.
    protocol : str
        String specifying the cloud bucket storage from which to retrieve
        the data. It must be specified if not searching data on local storage.
        Use `himawari_api.available_protocols()` to retrieve available protocols.
    fs_args : dict, optional
        Dictionary specifying optional settings to initiate the fsspec.filesystem.
        The default is an empty dictionary. Anonymous connection is set by default.
    satellite : str
        The name of the satellite.
        Use `himawari_api.available_satellites()` to retrieve the available satellites.
    product_level : str
        Product level.
        See `himawari_api.available_product_levels()` for available product levels.
    product : str
        The name of the product to retrieve.
        See `himawari_api.available_products()` for a list of available products.
    sector : str
        The acronym of the AHI sector for which to retrieve the files.
        See `himawari_api.available_sectors()` for a list of available sectors.
    filter_parameters : dict, optional
        Dictionary specifying option filtering parameters.
        Valid keys includes: `channels`, `scan_modes`, `scene_abbr`.
        The default is a empty dictionary (no filtering).
    connection_type : str, optional
        The type of connection to a cloud bucket.
        This argument applies only if working with cloud buckets (base_dir is None).
        See `himawari_api.available_connection_types` for implemented solutions.

    Returns
    -------
    fpath_dict : dict
        Dictionary with structure {<datetime>: [fpaths]}

    """
    sector = _check_sector(sector)
    product_level = _check_product_level(product_level)
    # Set time precision to minutes
    start_time = _check_time(start_time)
    start_time = start_time.replace(microsecond=0, second=0)
    # Get closest time and check is as start_time (otherwise warning)
    closest_time = find_closest_start_time(
        time=start_time,
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        filter_parameters=filter_parameters,
    )
    # Check start_time is the precise start_time of the file
    if check_consistency and closest_time != start_time:
        raise ValueError(
            f"start_time='{start_time}' is not an actual start_time. "
            f"The closest start_time is '{closest_time}'"
        )
    # Retrieve timedelta conditioned to sector type
    timedelta = _get_acquisition_max_timedelta(sector)
    # Define start_time and end_time
    start_time = closest_time
    end_time = closest_time + timedelta * (N+1) # +1 for when include_start_time=False
    # Retrieve files
    fpath_dict = find_files(
        base_dir=base_dir,
        protocol=protocol,
        fs_args=fs_args,
        satellite=satellite,
        product_level=product_level,
        product=product,
        sector=sector,
        start_time=start_time,
        end_time=end_time,
        filter_parameters=filter_parameters,
        group_by_key="start_time",
        connection_type=connection_type,
        verbose=False,
    )
    # List previous datetime
    list_datetime = sorted(list(fpath_dict.keys()))
    if not include_start_time:
        list_datetime.remove(closest_time)
    list_datetime = sorted(list_datetime)
    # Check data availability
    if len(list_datetime) == 0:
        raise ValueError(f"No data available between {start_time} and {end_time}.")
    if len(list_datetime) < N:
        raise ValueError(
            f"No {N} timesteps available between {start_time} and {end_time}."
        )
    # Select N most recent start_time
    list_datetime = list_datetime[0:N]
    # Select files for N most recent start_time
    fpath_dict = {tt: fpath_dict[tt] for tt in list_datetime}
    # ----------------------------------------------------------
    # Perform consistency checks
    if check_consistency:
        # Check for interval regularity
        if not include_start_time: 
            list_datetime = list_datetime + [closest_time]
        _check_interval_regularity(list_datetime)

    # ----------------------------------------------------------
    # Return files dictionary
    return fpath_dict


####--------------------------------------------------------------------------.
#### Output options
def _add_nc_bytes(fpaths):
    """Add `#mode=bytes` to the HTTP netCDF4 url."""
    fpaths = [fpath + "#mode=bytes" for fpath in fpaths]
    return fpaths


def _set_connection_type(fpaths, satellite, protocol=None, connection_type=None):
    """Switch from bucket to https connection for protocol 's3'."""
    if protocol is None:
        return fpaths
    if protocol == "file":
        return fpaths
    # here protocol s3
    if connection_type == "bucket":
        return fpaths
    if connection_type in ["https", "nc_bytes"]:
        if isinstance(fpaths, list):
            fpaths = _switch_to_https_fpaths(fpaths, protocol=protocol)
            if connection_type == "nc_bytes":
                fpaths = _add_nc_bytes(fpaths)
        if isinstance(fpaths, dict):
            fpaths = {
                tt: _switch_to_https_fpaths(l_fpaths, protocol=protocol)           
                for tt, l_fpaths in fpaths.items()
            }
            if connection_type == "nc_bytes":
                fpaths = {
                    tt: _add_nc_bytes(l_fpaths) for tt, l_fpaths in fpaths.items()
                }
        return fpaths
    else:
        raise NotImplementedError(
            "'bucket','https', 'nc_bytes' are the only `connection_type` available."
        )
