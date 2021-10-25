# Use this program under the terms of GNU GPLv3 or any later version.
import os
from pathlib import Path
import json
import requests
import re
from datetime import date as Date
from threading import Thread


MAX_BLOB_SIZE = 2097152
server = "http://localhost:5279"

try:
  lbrynet_dir = requests.post(server, json={"method":"settings_get", "params":{}}).json()["result"]["data_dir"] + "/"
  blobfiles_dir = lbrynet_dir + "blobfiles/"
except:
  input("Some error, lbrynet isn't probably running. Exiting...")
  exit(1)

local_claims = []
threads =[]
blobs = []
blob_files = []

class Blob:
  def __init__(self, blob_data):
    self.hash = blob_data["hash"]
    self.size = blob_data["size"]
    self.dates = [blob_data["date"]]
    self.claim = {}
    self.count = 1

    threads.append(Thread(target=self.findSdHash))
    threads[-1].start()

  def addBlob(self, blob_date):
    self.dates.append(blob_date)
    self.count += 1

  def findSdHash(self):
    if self.size < MAX_BLOB_SIZE:
      for blob_file in blob_files:
        if re.match(self.hash, blob_file["name"]):
          self.getClaim(blob_file["name"])
          return
    for blob_file in blob_files:
      self.findFromSortedList(blob_file)

  def findFromSortedList(self, blob_file):
    blobs = blob_file["blobs"]
    sd_hash = blob_file["name"]

    # Maximum values will never be checked, so these will probably work
    max_blob = len(blobs)
    min_blob = -1

    while max_blob - min_blob != 1:
      check_blob = min_blob + int((max_blob - min_blob)/2)
      check_blob_hash = blobs[check_blob]["blob_hash"]
      if re.match(self.hash, check_blob_hash):
        self.getClaim(sd_hash)
        return
      elif self.hash > check_blob_hash:
        min_blob = check_blob
      elif self.hash < check_blob_hash:
        max_blob = check_blob

  def getClaim(self, sdhash):
    for claim in local_claims:
      if claim["sd_hash"] == sdhash:
        self.claim = claim
        return

def blobExists(blob_data):
  for blob in blobs:
    if blob.hash == blob_data["hash"]:
      blob.addBlob(blob_data["date"])
      return True
  return False

def getSentBlobs():
  log_postfix = ""
  log_version = 0
  while True:
    log_file = lbrynet_dir + "lbrynet.log" + log_postfix
    try:
      with open(log_file, 'r') as file:
        for line in file.readlines():
          if "blob_exchange.server:106:" in line:
            blob_hash = line.split()[5]
            blob_size = int(line.split()[6].lstrip('('))
            blob_data = {"date": {"day": line.split()[0], "time": line.split()[1]},
                         "size": blob_size,
                         "hash": blob_hash}
            if not blobExists(blob_data):
              blobs.append(Blob(blob_data))
      log_version += 1
      print("Log version: %s read..." % log_version)
      log_postfix = "." + str(log_version)
    except FileNotFoundError:
      return

def getClaimsAndBlobs():
  server = "http://localhost:5279"
  method = "file_list"
  params = {"page_size": 9999999}
  response = requests.post(server, json={"method": method, "params": params}).json()
  for item in response["result"]["items"]:
    local_claims.append(item)
    sd_hash = item["sd_hash"]
    file_path = Path(blobfiles_dir + sd_hash)
    try:
      with open(file_path, 'r') as blob:
        blob_json = json.load(blob)
        blob_json["blobs"].remove(blob_json["blobs"][-1]) # Last item isn't blob
        blob_json["blobs"].sort(key=lambda blob: blob["blob_hash"])
        blob_files.append({"name": sd_hash, "blobs": blob_json["blobs"]})
    except FileNotFoundError:
      pass

##### STARTS FROM HERE ################
getClaimsAndBlobs()
getSentBlobs()

#### Wait for stuff to finish ###
for thread in threads:
  thread.join()

############### Extract data and write it to file #############################
total_data = 0
for blob in blobs:
  total_data += blob.size * blob.count
total_data = total_data/1000000

days = {}
files_today = {}
for blob in blobs:
    for date in blob.dates:
      try:
        days[date["day"]] += blob.size
      except KeyError:
        days[date["day"]] = blob.size

      if date["day"] == str(Date.today()):
        try:
          channel = blob.claim["channel_name"]
        except KeyError:
          channel = "Unknown channel"
        try:
          title = blob.claim["metadata"]["title"]
        except KeyError:
          title = "Unknown files"
        try:
          files_today["%s: %s" % (channel, title)] += blob.size
        except KeyError:
          files_today["%s: %s" % (channel, title)] = blob.size
try:
  total_today = days[str(Date.today())] / 1000000
except KeyError:
  total_today = 0

files = {}
for blob in blobs:
  try:
    channel = blob.claim["channel_name"]
  except KeyError:
    channel = "Unknown channel"
  try:
    title = blob.claim["metadata"]["title"]
  except KeyError:
    title = "Unknown files"
  try:
    files["%s: %s" % (channel, title)] += blob.size * blob.count
  except KeyError:
      files["%s: %s" % (channel, title)] = blob.size * blob.count

channels = {}
channels["Unknown Channel"] = 0 # For deleted files
for blob in blobs:
  try:
    channels[blob.claim["channel_name"]] += blob.size * blob.count
  except KeyError:
    try:
      channels[blob.claim["channel_name"]] = blob.size * blob.count
    except KeyError:
      channels["Unknown Channel"] += blob.size * blob.count

# Do some sorting and filtering
max_files_count = 25
max_channels_count = 25
days = {k: v/1000000 for k,v in days.items()}
days = dict(sorted(days.items(), key=lambda x: x[0]))
files = {k: v/1000000 for k,v in files.items()}
files = dict(sorted(files.items(), key=lambda x: x[1], reverse=True)[:max_files_count])
files_today = {k: v/1000000 for k,v in files_today.items()}
files_today = dict(sorted(files_today.items(), key=lambda x: x[1], reverse=True)[:max_files_count])
channels = {k: v/1000000 for k,v in channels.items()}
channels = dict(sorted(channels.items(), key=lambda x: x[1], reverse=True)[:max_channels_count])

minFileSize = 0
minChannelSize = 0
files = dict(filter(lambda elem: elem[1] > minFileSize, files.items()))
channels = dict(filter(lambda elem: elem[1] > minChannelSize, channels.items()))

output_file = "LBRY-host-statics.html"
f = open(output_file, 'w')
f.write("""<!DOCTYPE html>
        <html>
          <meta charset="utf-8"/>
          <style>
           canvas {{
            margin: 0;
            position: relative;
            left: 50%;
            -ms-transform: translateX(-50%);
            transform: translateX(-50%);
                    }}
          </style>
          <script src=\"https://cdnjs.cloudflare.com/ajax/libs/Chart.js/2.5.0/Chart.min.js\"></script>
          <body>
            <canvas id=\"dataByDate\"style=\"max-width:1200px\"></canvas>
            <canvas id=\"mostHostedByFile\"style=\"max-width:1200px;\"></canvas>
            <canvas id=\"mostHostedByChannel\"style=\"max-width:1200px;\"></canvas>
            <canvas id=\"hostedToday\"style=\"max-width:1200px;\"></canvas>
            <script>
             var days={days};
             new Chart(\"dataByDate\",{{
             type:\"bar\",
             data:{{
              labels:Object.keys(days),
              datasets:[{{
                backgroundColor:\"green\",
                data:Object.values(days)}}]}},
              options:{{legend:{{display:false}}, title:{{display:true,text:\"Known hosted data in MB. Total: {totalData} \"}}}}}});

             var files={files};
             new Chart(\"mostHostedByFile\",{{
             type:\"horizontalBar\",
             data:{{
              labels:Object.keys(files),
              datasets:[{{
                backgroundColor:\"green\",
                data:Object.values(files)}}]}},
              options:{{legend:{{display:false}},responsive: true, title:{{display:true,text:\"{maxFiles} most hosted files (>{minFileSize}MB)\"}}}}}});

             var channels={channels};
             new Chart(\"mostHostedByChannel\",{{
             type:\"horizontalBar\",
             data:{{
              labels:Object.keys(channels),
              datasets:[{{
                backgroundColor:\"green\",
                data:Object.values(channels)}}]}},
              options:{{legend:{{display:false}},responsive: true, title:{{display:true,text:\"{maxChannels} most hosted channels (>{minChannelSize}MB)\"}}}}}});

             var files_today={files_today};
             new Chart(\"hostedToday\",{{
             type:\"horizontalBar\",
             data:{{
              labels:Object.keys(files_today),
              datasets:[{{
                backgroundColor:\"green\",
                data:Object.values(files_today)}}]}},
              options:{{legend:{{display:false}},responsive: true, title:{{display:true, text:\" Files hosted today in MB. Total: {totalToday}\"}}}}}});
            </script>
          </body>
        </html>""".format(
          days=str(days),
          files=str(files),
          channels=str(channels),
          files_today=str(files_today),
          minFileSize = minFileSize,
          minChannelSize = minChannelSize,
          maxFiles = min(len(files),max_files_count),
          maxChannels = min(len(channels),max_channels_count),
          totalData = "{0:.2f}GB".format(total_data/1000) if total_data > 1000 else "{0:.2f}MB".format(total_data),
          totalToday = "{0:.2f}GB".format(total_today/1000) if total_data > 1000 else "{0:.2f}MB".format(total_today)))

f.close()
print("Created file: {}".format(output_file))

