#!/usr/bin/python3
# script version and log level
script_version = "250128.18"
log_level = "DEBUG" # DEBUG INFO WARN ERROR

'''
ARGUMENTS RECEIVED FROM VANTAGE:
1. Item ID
3. Environment

WHAT THE SCRIPT DOES:
-Gets secrets from Vault
-Gets stuff from VS
  -Subtype
  -Audio codec
  -Audio profile number
    -If number is 0, quits due to unknown profile
    -If number connotes weird profile, quits
  -Shape document
-Calculates track/channel layout
-Calculates what numerical information to send to Elemental to ensure a correct transcode output
-Builds and stamps metadata field with this info
  -{subtype}_qc_orig_audio_analysis_elemental_audio_selector_snippet
'''
###CHANGE LOG###
'''
version 250128.18 - initial version
'''

#native imports
import sys
import xml.etree.ElementTree as ET
import traceback

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

# args to variables:
script_name =  cms_integration_logging.get_script_name(sys.argv[0])
arg_problem = False
if len(sys.argv) == 3:
    item_id = sys.argv[1]
    env = sys.argv[2].lower()
else:
	if len(sys.argv) > 3:
		arg_problem = "Too many args provided!"
	else:
		arg_problem = "Not enough args provided!"

# logger setup - must have cms_integration_logging imported in project imports
# extras used in the json logger
extras = {"cms_environment": env, "script_version": script_version}
logger = cms_integration_logging.set_up_logging(sys.argv[0],env,script_version,log_level)

# start logging
logger.info(f'COMMENCING {script_name}.', extra=extras)
# bail out now if there was a problem with the number of args.
if arg_problem:
	logger.error(arg_problem)
	exit(1)

# log arg variables
logger.info(f'{env} provided as environment.', extra=extras)
logger.info(f'{item_id} provided as the item.', extra=extras)

# project imports
import eng_vault_agent # need this for pretty much everything to get auth and ip addresses
import eng_vs_token # vs tools
from audio_profiles import profiles, channel_counts, channel_orders, channel_order_index, valid_pairings, ats_snippets

# custom functions
def remix_needed(codec,track_layout):
  if track_layout in ['Stereo','Mono']:
    # stereo or mono never need remix
    return False
  elif valid_pairings[codec] == track_layout.split('_')[-1]:
    return False
  else:
    return True

def is_zeroth_audio(shape):
  # is first track A0 or A1?
  for audio_component in shape.findall('shape/audioComponent'):
    track = audio_component.find('itemTrack').text
    track_number = int(track.replace("A",""))
    if track_number == 0:
      return True
  return False

def elemental_audio_selector(vs_token_data):
  vs = vs_token_data['vs']
  token = vs_token_data['token']
# add AKAs for pcm to this list if needed in the future
  aka_pcm = ['s302m']
  
  subtype = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, 'file_information_subtype')
  if 'Mezz' in subtype:
    subtype = 'mezz'
  else:
    subtype = 'deriv'

  shape = eng_vs_token.get_shape_document(vs, token, item_id, 'original')
  audio_codec = eng_vs_token.get_system_metadata_value(vs_token_data, item_id, 'originalAudioCodec').split('_')[0]
  if audio_codec in aka_pcm:
    audio_codec = 'pcm'
  snippets = []

  audio_profile_number = eng_vs_token.get_group_metadata_value(vs_token_data, item_id, f'{subtype}_qc_orig_audio_profile_number')
  logger.info(f'Audio profile number is {audio_profile_number}')

  # audio_profile 12 would result in {'track_1':'5.1_SMPTE','track_2':'Stereo'}
  audio_components = shape.findall('shape/audioComponent')
  track_channel_pairings = {}
  track_channel_counts = {}
  number_of_tracks = len(audio_components)

  # quit now if audio profile number is 0 or one of the weird ones
  if audio_profile_number == '0':
    logger.warning(f'Audio profile unknown. Quitting')
    exit(0)
  if int(audio_profile_number) in [200, 201, 203, 204, 205, 206]:
    if int(audio_profile_number) not in [200, 205, 206]:
      data = ats_snippets[int(audio_profile_number)][str(number_of_tracks)]
    else:
      data = ats_snippets[int(audio_profile_number)]
    return data, subtype
  
  audio_profile = profiles[int(audio_profile_number)]
  logger.info(f'Audio profile is {audio_profile}')

  if is_zeroth_audio(shape):
    index_corrector = -1
  else:
    index_corrector = 0
  current_track = 1
  tracks_to_skip = 0
  for index, profile in enumerate(audio_profile, start=1):
    order = channel_orders[audio_profile[f'track_{index}']]
    logger.info(f'audio profile track {index} order: {order}')

    # if the audio_profile is {'track_1':'5.1_SMPTE','track_2':'Stereo'}
    # and index is 1 (first pass)
    # then audio_profile['track_1'] returns '5.1_SMPTE'
    # then order would = channel_orders['5.1_SMPTE'] output which is:
    # ['Left','Right','Center','LFE','Left Surround','Right Surround']

    # next compose the track_channel_pairings dict
    # add a list for the current track
    track_channel_pairings[f'track_{index}'] = []

    logger.info(f'audio profile track channel pairings prep: {track_channel_pairings}')

    channel_count = 1

    # get the channel count for the first actual track from the shape doc
    # we are correcting the index based on new media info in vs zeroth tracks
    channels = shape.find(f'shape/audioComponent[itemTrack="A{current_track+index_corrector}"]/channelCount').text # add -1 to here to select zeroth based when appropriate.
    logger.info(f'channels found in track {current_track}: {channels}')

    channels = str(int(channels) - tracks_to_skip)
    for position in order:
      # in our example the order was ['Left','Right','Center','LFE','Left Surround','Right Surround']
      if channel_count < int(channels):
        # there are more channels in the track
        if str(current_track) not in track_channel_pairings[f'track_{index}']:
          # i think this is for when we have multiple mono tracks in single track (discrete audio)
          track_channel_pairings['track_%s' % index].append(str(current_track))
          logger.info(f'track_channel_pairings: {track_channel_pairings}')
        channel_count += 1
      elif channel_count == int(channels):
        # when a channel count is equal to the number of channels (the track is done)
        # or it could be a mono track profile
        if str(current_track) not in track_channel_pairings[f'track_{index}']:
          track_channel_pairings[f'track_{index}'].append(str(current_track))
          logger.info(f'track_channel_pairings: {track_channel_pairings}')
        current_track += 1
        channel_count = 1
        tracks_to_skip = 0
      else:
        current_track += 1
        channel_count = 1
        tracks_to_skip = 0
    tracks_to_skip += channel_count - 1

  for component in audio_components:
    if is_zeroth_audio(shape):
      logger.info('Track 0')
      track_number = int(component.find('itemTrack').text.replace('A','')) + 1
    else:
      track_number = int(component.find('itemTrack').text.replace('A',''))
    logger.info(f'track {track_number}')
    track_channel_counts[track_number] = int(component.find('channelCount').text)
    logger.info(f'Track channel counts: {track_channel_counts}')

  tracks_to_skip = 0

  for index, profile in enumerate(audio_profile,start=1):
    profile = audio_profile[f'track_{index}']
    logger.info(f'Profile: {profile}')
    remix = remix_needed(audio_codec,profile)
    logger.info(f'Remix needed: {remix}')
    snippet = ET.Element('audio_selector')
    default_selection = ET.SubElement(snippet,'default_selection')
    default_selection.text = 'true'
    infer_external_filename = ET.SubElement(snippet,'infer_external_filename')
    infer_external_filename.text = 'false'
    order = ET.SubElement(snippet,'order')
    order.text = str(index)
    program_selection = ET.SubElement(snippet,'program_selection')
    program_selection.text = '1'
    selector_type = ET.SubElement(snippet,'selector_type')
    selector_type.text = 'track'
    track = ET.SubElement(snippet,'track')
    track.text = ','.join(track_channel_pairings[f'track_{index}'])

    channel_sum = 0
    for track in track_channel_pairings[f'track_{index}']:
      channel_sum += track_channel_counts[int(track)]

    unwrap_smpte337 = ET.SubElement(snippet,'unwrap_smpte337')
    unwrap_smpte337.text = 'false'

    if channel_sum > channel_counts[profile.split('_')[0]]:
      remix = True

    if remix:
      total_channels = str(channel_counts[profile.split('_')[0]])
      if profile in ['Stereo','Mono']:
        target_order = profile
      else:
        target_order = f'{profile.split("_")[0]}_{valid_pairings[audio_codec]}'
      remix_settings = ET.SubElement(snippet,'remix_settings')
      channels_in = ET.SubElement(remix_settings,'channels_in')
      channels_in.text = str(channel_sum)
      channels_out = ET.SubElement(remix_settings,'channels_out')
      channels_out.text = total_channels
      channel_mapping = ET.SubElement(remix_settings,'channel_mapping')
      for channel_num, position in enumerate(channel_orders[target_order]):
        target_channel = str(channel_order_index[profile][position] + tracks_to_skip)
        out_ch = ET.SubElement(channel_mapping,f'out_ch_{channel_num}')
        for num in range(0,channel_sum):
          in_ch = ET.SubElement(out_ch,f'in_ch_{num}')
          if str(num) == target_channel:
            in_ch.text = '0'
          else:
            in_ch.text = '-60'
    name = ET.SubElement(snippet,'name')
    name.text = f'input_1_audio_selector_{index - 1}'
    snippets.append(ET.tostring(snippet, encoding='unicode'))
    if (channel_counts[profile.split('_')[0]] + tracks_to_skip) == channel_sum:
      tracks_to_skip = 0
    else:
      tracks_to_skip += channel_counts[profile.split('_')[0]]

  return ''.join(snippets), subtype

def main():
  # get_vault_secret_data function returns a dict  
  secret_path = f'v1/secret/{env}/vidispine/vantage'
  vs_secret_data = eng_vault_agent.get_secret(secret_path)
  username = vs_secret_data["username"]
  password = vs_secret_data["password"]
  vs = vs_secret_data["api_url"]
  vs_auth = eng_vs_token.get_basic_auth(username,password)
  ttl = 10
  token_data = eng_vs_token.get_token_no_auto_refresh(vs, vs_auth, ttl)
  if not token_data:
    logger.error("Didn't get token data from vidispine?")
    exit(2)
  data, subtype = elemental_audio_selector(token_data)
  m = eng_vs_token.make_group_metadata_doc(f'{subtype}_qc_orig_audio_analysis', f'{subtype}_qc_orig_audio_analysis_elemental_audio_selector_snippet', data)
  r = eng_vs_token.put_item_metadata(token_data, item_id, m)
  logger.info(f'Metadata update response code {r}')

try:
	main()
	exit(0)
except Exception as e:
	logger.error(traceback.format_exc())
	exit(1)