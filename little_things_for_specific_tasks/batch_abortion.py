#!usr/bin/python3
'''
This little guy is a mass-abortion tool:

-Queries Vidispine for a current list of all jobs with a status of WAITING,
-Compiles a list of all job IDs returned;
-Sends an abort request for each ID
-Prints a list of aborted IDs upon request of Co-Pilot
-Is done

This is pretty much for one-time use, so we're assuming that we're working in prod.
'''

import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass
import requests

# global variables
ENVIRONMENT = 'prod'

script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')

# logging setup
if not os.path.exists(log_file):
    with open(log_file, 'w', encoding='utf-8'):
        pass

logging.basicConfig(
    filename=log_file,
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s')

def xml_prep(res):
    '''Gets rid of namespace in XML returns for easier parsing'''
    res = res.content
    res = res.decode(encoding='utf-8', errors='strict')
    # because I hate dealing with the namespace in ET
    res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
    res = res.encode(encoding='utf-8', errors='strict')
    res = ET.fromstring(res)
    return res

def get_variables_from_config(environment,proxy_config):
    '''Gets VS IP and auth string from config file'''
    env = proxy_config.findall('environment')
    for e in env:
        if e.find('short_name').text == environment:
            vs = e.find('vidispine/ip_address').text
            vs_auth = e.find('vidispine/auth').text
            break
    return vs,vs_auth

def get_job_list(vs,vs_auth) -> list:
    '''Queries VS for a list of all jobs with status WAITING; returns list'''
    waiting_jobs = []
    url = vs+'API/job;state=WAITING;type=EXPORT;user=false?timezone=GMT-4&number=1000'
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = requests.get(url, headers=headers)
    job_list = xml_prep(response)
    jobs = job_list.findall('job')
    for job in jobs:
        job_id = job.find('jobId').text
        waiting_jobs.append(job_id)
    return waiting_jobs

def delete_job(vs,vs_auth,job_id) -> bool:
    '''Sends an abort request for a given job ID; returns True if successful'''
    del_url = vs+'API/job/'+job_id
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = requests.delete(del_url, headers=headers)
    if response.status_code == 200:
        logging.info('Successfully aborted job ID %s', job_id)
        return True
    else:
        logging.error('Failed to abort job ID %s. Response code %s', job_id,response.status_code)
        return False

def main():
    '''the biggun'''
    user = getpass.getuser()
    logging.info('%s: COMMENCING: %s executed by %s', ENVIRONMENT,script_file_name,user)
    proxy_config = ET.parse(proxy_config_file)
    vs,vs_auth = get_variables_from_config(ENVIRONMENT,proxy_config)
    waiting_jobs = get_job_list(vs,vs_auth)
    logging.info('%s: Found %s jobs with status WAITING', ENVIRONMENT,len(waiting_jobs))
    for job in waiting_jobs:
        if delete_job(vs,vs_auth,job):
            print(f'Aborted job ID {job}')
        else:
            print(f'Failed to abort job ID {job}. Check log for details.')
            exit(1)
    print('All done.')
    logging.info('ALL DONE')
    sys.exit(0)

if __name__ == '__main__':
    main()
