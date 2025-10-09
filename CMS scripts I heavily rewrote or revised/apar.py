#!/usr/bin/python3
# script version and log level
script_version = "250107.17"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
2. Environment

WHAT THIS SCRIPT DOES:
-Introduces a dictionary of acceptable APAR profiles (Adjusted Pixel Aspect Ratio)
    -Profiles dict contains three sub-dicts: SD/HD/UHD
-Gets the item's field values from Vidispine
    -file_information_subtype
        -From this field, declares a subtype variable (mezz/deriv) and a video_format variable (SD/HD/UHD)
    -originalHeight
    -originalWidth
    -{subtype}_qc_orig_apar_pixel_aspect_ratio
    -{subtype}_qc_orig_letterbox_analysis_crop_top
    -{subtype}_qc_orig_letterbox_analysis_crop_bottom
    -{subtype}_qc_orig_letterbox_analysis_crop_left
    -{subtype}_qc_orig_letterbox_analysis_crop_right
-Puts together the APAR by:
    -subtracting the top/bottom crop values from originalHeight value
    -multiplying the originalWidth and left/right crop values by the pixel_aspect_ratio
    -subtracting the adjusted crop values from the adjusted width
    -overall APAR = adjusted width divided by adjusted height
-Cross-checks the appropriate sub-dict for profile that matches the APAR value
    -Profile match occurs if APAR falls between the 'min' and 'max' values of a given profile
    -If match, profile number = profile key and profile description = profile 'description' value
    -If no match, profile number = 0 and profile description = 'This ain't right'
-Stamps item's metadata with APAR, profile number, and profile description
'''

###CHANGE LOG###
'''
version 250107.17 - initial version
'''

# native imports
import sys

# custom support packages live in the scripts/packages/ directory
# add path to packages for import
script_path = sys.argv[0]
if 'linux' in sys.platform or 'darwin' in sys.platform:
    packages_path = script_path[:script_path.rfind('/scripts/')]+'/packages/'
else:
    packages_path = script_path[:script_path.rfind('\\scripts\\')]+'\\packages\\'
sys.path.insert(0,packages_path)

# add variable for path to crt_file (DigiCertCA.crt) which is in the packages path above
crt_file = packages_path + 'DigiCertCA.crt'

# import logging module
import cms_integration_logging # need this for everything

# args to variables
arg_problem = False
if len(sys.argv) > 3:
    arg_problem = "Too many args provided!"
elif len(sys.argv) < 3:
    arg_problem = "Not enough args provided!"
else:
    # item id and workflow
    script_name =  cms_integration_logging.get_script_name(sys.argv[0])
    item_id = sys.argv[1]
    env = sys.argv[2].lower()

# logger setup - must have cms_integration_logging imported
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools

# reference dict
apar_profiles = {
    'UHD':{
    1:{'min':1.76,'max':1.79,'description':'Fullscreen UHD 16:9'},
    2:{'min':2.34,'max':2.40,'description':'Letterboxed Current US Widescreen Cinema Standard'},
    3:{'min':1.32,'max':1.35,'description':'Pillarboxed 4:3 in UHD frame'},
    4:{'min':1.84,'max':1.86,'description':'Letterboxed (slight) Old US Widescreen Cinema Standard'},
    5:{'min':0.99,'max':1.01,'description':'Pillarboxed Square'},
    6:{'min':1.36,'max':1.38,'description':'Pillarboxed Academy 11:8'},
    7:{'min':1.42,'max':1.44,'description':'Pillarboxed Imax'},
    8:{'min':2.75,'max':2.77,'description':'Letterboxed Ultra Panavision 70'},
    9:{'min':1.55,'max':1.57,'description':'Pillarboxed 14:9'}
    },
    'HD':{
    1:{'min':1.76,'max':1.79,'description':'Fullscreen HD 16:9'},
    2:{'min':2.34,'max':2.40,'description':'Letterboxed Current US Widescreen Cinema Standard'},
    3:{'min':1.32,'max':1.35,'description':'Pillarboxed 4:3 in HD frame'},
    4:{'min':1.84,'max':1.86,'description':'Letterboxed (slight) Old US Widescreen Cinema Standard'},
    5:{'min':0.99,'max':1.01,'description':'Pillarboxed Square'},
    6:{'min':1.36,'max':1.38,'description':'Pillarboxed Academy 11:8'},
    7:{'min':1.42,'max':1.44,'description':'Pillarboxed Imax'},
    8:{'min':2.75,'max':2.77,'description':'Letterboxed Ultra Panavision 70'},
    9:{'min':1.55,'max':1.57,'description':'Pillarboxed 14:9'}
    },
    'SD':{
    10:{'min':1.76,'max':1.79,'description':'Letterboxed 16:9'},
    11:{'min':2.34,'max':2.40,'description':'Letterboxed Current US Widescreen Cinema Standard'},
    12:{'min':1.32,'max':1.35,'description':'Fullscreen SD'},
    13:{'min':1.84,'max':1.86,'description':'Letterboxed Old US Widescreen Cinema Standard'},
    14:{'min':0.99,'max':1.01,'description':'Pillarboxed Square'},
    15:{'min':1.36,'max':1.38,'description':'Letterboxed (slight) Academy 11:8'},
    16:{'min':1.42,'max':1.44,'description':'Letterboxed (slight) Imax'},
    17:{'min':2.75,'max':2.77,'description':'Letterboxed Ultra Panavision 70'},
    18:{'min':1.55,'max':1.57,'description':'Letterboxed 14:9'}
    }
}

# and here we go! secret data first
secret_path = f'v1/secret/{env}/vidispine/vantage'
vs_secret_data = eng_vault_agent.get_secret(secret_path)
username = vs_secret_data["username"]
password = vs_secret_data["password"]
vs = vs_secret_data["api_url"]
seconds = 60
basic_auth = eng_vs_token.get_basic_auth(username,password)
token_data = eng_vs_token.get_token_no_auto_refresh(vs,basic_auth,seconds)
if not token_data:
    logger.error("Didn't get token data from vidispine?")
    exit(2)

# subtype/format first
subtype = eng_vs_token.get_group_metadata_value(token_data,item_id,'file_information_subtype')

if 'UHD' in subtype:
    video_format = 'UHD'
elif 'HD' in subtype and 'UHD' not in subtype:
    video_format = 'HD'
else:
    video_format = 'SD'

if 'mezz' in subtype.lower():
    subtype = 'mezz'
elif 'deriv' in subtype.lower():
    subtype = 'deriv'

logger.warning(f'Calculating APAR for {item_id}, Video Format {video_format}, Subtype {subtype.capitalize()}')

height = int(eng_vs_token.get_system_metadata_value(token_data,item_id,'originalHeight'))
width = int(eng_vs_token.get_system_metadata_value(token_data,item_id,'originalWidth'))
pixel_aspect_ratio = float(eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_apar_pixel_aspect_ratio'))

logger.warning(f'Height {height}, Width {width}, PAR {pixel_aspect_ratio}')

crop_top = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_letterbox_analysis_crop_top')
crop_top = int(crop_top) if crop_top else 0

crop_bottom = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_letterbox_analysis_crop_bottom')
crop_bottom = int(crop_bottom) if crop_bottom else 0

crop_left = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_letterbox_analysis_crop_left')
crop_left = int(crop_left) if crop_left else 0

crop_right = eng_vs_token.get_group_metadata_value(token_data,item_id,f'{subtype}_qc_orig_letterbox_analysis_crop_right')
crop_right = int(crop_right) if crop_right else 0

logger.warning(f'Crop Top {crop_top}, Crop Bottom {crop_bottom}, Crop Left {crop_left}, Crop Right {crop_right}')

apar_height = height - (crop_top + crop_bottom)
apar_width = (width * pixel_aspect_ratio) - ((crop_right + crop_left) * pixel_aspect_ratio) 

logger.warning(f'APAR Height {apar_height}, APAR Width {apar_width}')

apar = apar_width / apar_height

logger.warning(f'APAR {apar}')
target_profile = None

for profile in apar_profiles[video_format]:
    p = apar_profiles[video_format][profile]
    if apar >= p['min'] and apar <= p['max']:
        target_profile = profile

if target_profile == None:
    profile_number = '0'
    profile_description = f'WARNING: An Active Picture Ratio of {round(apar,2)} is not to standard and should be examined.'
else:
    profile_number = str(target_profile)
    profile_description = apar_profiles[video_format][target_profile]['description']

logger.warning(f'Profile Number {profile_number}, Description {profile_description}')

profile_number_update = {'group':f'{subtype}_qc_orig_apar','field':f'{subtype}_qc_orig_apar_profile_number','value':profile_number}
description_update = {'group':f'{subtype}_qc_orig_apar','field':f'{subtype}_qc_orig_apar_profile_description','value':profile_description}
apar_update = {'group':f'{subtype}_qc_orig_apar','field':f'{subtype}_qc_orig_apar','value':str(round(apar,2))}

a_metadata = eng_vs_token.make_group_metadata_doc(profile_number_update['group'],profile_number_update['field'],profile_number_update['value'])
b_metadata = eng_vs_token.make_group_metadata_doc(description_update['group'],description_update['field'],description_update['value'])
c_metadata = eng_vs_token.make_group_metadata_doc(apar_update['group'],apar_update['field'],apar_update['value'])
a = eng_vs_token.put_item_metadata(token_data,item_id,a_metadata)
b = eng_vs_token.put_item_metadata(token_data,item_id,b_metadata)
c = eng_vs_token.put_item_metadata(token_data,item_id,c_metadata)

logger.warning(f'Status for Profile Num Update {a}, Description Update {b}, APAR Update {c}')
exit(0)