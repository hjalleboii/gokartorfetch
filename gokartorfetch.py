#!/bin/python3
import requests
from PIL import Image, ImageDraw
import os
import math

tempfolder = "temp"
os.makedirs(tempfolder, exist_ok=True)

from bs4 import BeautifulSoup
from datetime import date
import json
import time

from pyproj import Transformer
import argparse




"""
{
    resolutions: [16384, 8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25, 0.125],
    origin: [265000, 7680000],
    bounds: L.bounds([255000, 6130000], [925000, 7680000])
}
"""

resolutions = [16384, 8192, 4096, 2048, 1024, 512, 256, 128, 64, 32, 16, 8, 4, 2, 1, 0.5, 0.25, 0.125]
origin_x = 265000
origin_y = 7680000
tS = 256
inputcoordinatesystem = "EPSG:4326"
mapcoordinatesystem = "EPSG:3006"




def get_with_backoff(url, max_retries=5):
    delay = 1
    for attempt in range(max_retries):
        response = requests.get(url)
        if response.status_code != 429:
            return response
        time.sleep(delay)
        delay *= 2  # exponential backoff
    raise Exception("Max retries exceeded")


def GetLatLonMinMax(lon0,lat0,lon1,lat1):
    return ((max(lon0,lon1),max(lat0,lat1)),(min(lon0,lon1),min(lat0,lat1)))

def GetLocalCoordinates(lon,lat):
    transformer = Transformer.from_crs(inputcoordinatesystem, mapcoordinatesystem, always_xy=True)
    x, y = transformer.transform(lon, lat)
    return (x,y)

def GetTileFileName(layer,level, tX,tY):
    return os.path.join(tempfolder,f"Tile_{layer}_{level}_{tY}_{tX}.png")

def GetAndSaveTile(layer,level, tX,tY):

    url = f"https://kartor.gokartor.se/{layer}/{level}/{tY}/{tX}.png"
    response = get_with_backoff(url)
    if  not response.ok:
        print(f"Failed to fetch {url}    Response: {response.status_code}")
        return -1
    with open(GetTileFileName(layer,level, tX,tY),"wb") as out:
        out.write(response.content)
    return 0


def tX_to_cx(tX,zoom):
    return origin_x+tX*tS*resolutions[zoom]

def tY_to_cy(tY,zoom):
    return origin_y-tY*tS*resolutions[zoom]

def cx_to_tX(cx,zoom):
    return (cx-origin_x)/(tS*resolutions[zoom])

def cy_to_tY(cy,zoom):
    return (origin_y-cy)/(tS*resolutions[zoom])


def ExportPGW(name,tYmax,tYmin,tXmax,tXmin,zoom):
    with open(name,"w") as pgw:
        pgw.write(str(resolutions[zoom]))
        pgw.write("\n")
        pgw.write(str(0))
        pgw.write("\n")
        pgw.write(str(0))
        pgw.write("\n")
        pgw.write(str(-resolutions[zoom]))
        pgw.write("\n")
        pgw.write(str(tX_to_cx(tXmin,zoom)))
        pgw.write("\n")
        pgw.write(str(tY_to_cy(tYmin,zoom)))
        pgw.write("\n")


def DrawNorthLines(image,declination_deg,spacing,width,zoom):
    sXm = spacing / math.cos(-declination_deg*math.pi/180)
    sXp = sXm/resolutions[zoom]
    imw,imh = image.size


    negative_count = (imh/math.tan((90+declination_deg)*math.pi/180))/sXp

    draw = ImageDraw.Draw(image)
    for i in range(-int(negative_count),int(imw/sXp)+1):
        draw.line((i*sXp,imh-1,imh/math.tan((90+declination_deg)*math.pi/180) + i*sXp,0),fill='black',width = max(1,int(width/resolutions[zoom])))
    return image

def GeneratetMap(tYmax,tYmin,tXmax,tXmin,zoom,layer):


    export = Image.new('RGB',((tXmax-tXmin+1)*tS,(tYmax-tYmin+1)*tS))


    for x in range(tXmin,tXmax+1):
        for y in range(tYmin,tYmax+1):
            if GetAndSaveTile(layer,zoom,x,y) == 0:
                image = Image.open(GetTileFileName(layer,zoom,x,y))
                export.paste(image,((x-tXmin)*tS,(y-tYmin)*tS,(x-tXmin+1)* tS,(y-tYmin+1)*tS))
            else: 
                print("skipping tile x:{x} y:{y}")
    return export


def zoom_range(value):
    ivalue = int(value)
    if 6 <= ivalue <= 15:
        return ivalue
    else:
        raise argparse.ArgumentTypeError("Zoom must be an integer between 6 and 15.")

def valid_layers(value):
    ivalue = str(value)
    values = ["Master"]
    if value in values:
        return ivalue
    else:
        raise argparse.ArgumentTypeError(f"Layer must be one of {values}")



def getmagneticdeclination(lat, lon):
    form = requests.get("https://www.ngdc.noaa.gov/geomag/calculators/declinationForm.shtml")
    soup = BeautifulSoup(form.text,'html.parser')
    input_key = soup.find('input',id='key')
    apikey = input_key.get('value')
    today = date.today()
    parameters = {"key":apikey,"lat1":lat,"lat1Hemisphere":"N","lon1":lon,"lon1Hemisphere":"W","model":"WMM","startYear":today.year,"startMonth":today.month,"startDay":today.day,"resultFormat":"json"}
    response = requests.get("https://www.ngdc.noaa.gov/geomag-web/calculators/calculateDeclination",params=parameters)
    json_data = json.loads(response.text)
    return json_data["result"][0]["declination"]


def parseargs():

    parser = argparse.ArgumentParser(description="Download maps from gokartor")

    parser.add_argument("-Z","--zoom",type=zoom_range,help="Zoom: Range 6-15. 15 is the highest resolutions and 6 the lowest.",default=15)


    parser.add_argument("-L", "--layer",type=valid_layers,help="Map Layer, valid layers: Master",default="Master")

    parser.add_argument("-N", "--name",type=str,help="Name of the output or object (string)",default="export")

    parser.add_argument("-C", "--coordinates",type=float,nargs=4,required=True,metavar=("LAT1", "LON1", "LAT2", "LON2"),help="Input coordinates: lat1 lon1 lat2 lon2")
    parser.add_argument("--northlinespacing",type=float,help="Spacing of northlines in meters, default 500m", default=500)
    parser.add_argument("--northlinewidth",type=float,help="Northline width in meters, default 3",default=3)
    return parser.parse_args()


def run(args):
    lat_0,lon_0,lat_1,lon_1 = args.coordinates
    (lonmax,latmax),(lonmin,latmin) = GetLatLonMinMax(lon_0,lat_0,lon_1,lat_1)
    cXmax,cYmax = GetLocalCoordinates(lonmax,latmax)
    cXmin,cYmin = GetLocalCoordinates(lonmin,latmin)
    #print(cXmin,cYmin)
    #print(cXmax,cYmax)
    tXmax = int(math.ceil(cx_to_tX(cXmax,args.zoom)))
    tYmin = int(math.floor(cy_to_tY(cYmax,args.zoom)))
    tXmin = int(math.floor(cx_to_tX(cXmin,args.zoom)))
    tYmax = int(math.ceil(cy_to_tY(cYmin,args.zoom)))
    #print(tYmax,tYmin,tXmax,tXmin)
    m = GeneratetMap(tYmax,tYmin,tXmax,tXmin,args.zoom,args.layer)
    DrawNorthLines(m,getmagneticdeclination(0.5*(lat_0+lat_1),0.5*(lon_0+lon_1)),args.northlinespacing,2,args.zoom)
    m.save(args.name+".png")
    ExportPGW(args.name+".pgw",tYmax,tYmin,tXmax,tXmin,args.zoom)
run(parseargs())
