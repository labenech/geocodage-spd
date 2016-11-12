#! /usr/bin/python3
import sys
import csv
import requests
import json
import sqlite3
import re

# effecture une req. sur l'API de géocodage
def geocode(api, params):
    r = requests.get(api, params)
    j = json.loads(r.text)
    if 'features' in j and len(j['features'])>0:
        return(j['features'][0])
    else:
        return(None)

def trace(txt):
    if False:
        print(txt)

score_min = 0.30

# URL à appeler pour géocodage BAN et BANO
addok_ban = 'http://localhost:7979/search/'
addok_bano = 'http://localhost:7878/search'

sirene_csv = csv.reader(open(sys.argv[1],'r'))
sirene_geo = csv.writer(open('geo-'+sys.argv[1],'w'))

# chargement de la liste des communes et lat/lon
communes = csv.DictReader(open('communes-plus-20140630.csv','r'))
commune_insee = []
commune_latitude = []
commune_longitude = []
for commune in communes:
    commune_insee.append(commune['\ufeffinsee'])
    commune_latitude.append(round(float(commune['lon_centro']),6))
    commune_longitude.append(round(float(commune['lat_centro']),6))

header = None
ok = 0
total = 0
numbers = re.compile('(^[0-9]*)')
stats = {'housenumber':0,'interpolation':0,'street':0,'locality':0,'municipality':0,'vide':0,'townhall':0}

for et in sirene_csv:
    if header is None:
        header = et+['longitude','latitude','geo_score','geo_type','geo_adresse','geo_id']
        sirene_geo.writerow(header)
    else:
        total = total + 1
        # géocodage de l'adresse géographique
        # au cas où numvoie contiendrait autre chose que des chiffres...
        numvoie = numbers.match(et[16]).group(0)

        indrep = et[17]
        typvoie = et[18]
        libvoie = et[19]

        if numvoie == '' and numbers.match(libvoie).group(0):
            numvoie = numbers.match(libvoie).group(0)
            libvoie = libvoie[len(numvoie):]


        # typvoie incorrect
        if typvoie == 'PRO':
            typvoie = 'PROM'

        # élimination des LD / LIEU-DIT des libellés
        if typvoie == 'LD':
            typvoie = ''
        libvoie = re.sub(r'^PRO ','PROMENADE ',libvoie)
        libvoie = re.sub(r'^LD ','',libvoie)
        libvoie = re.sub(r'^LIEU(.|)DIT ','',libvoie)
        libvoie = re.sub(r'^ADRESSE INCOMPLETE.*','',libvoie)
        libvoie = re.sub(r'^SANS DOMICILE FIXE','',libvoie)

        # ou de la ligne 4 normalisée
        ligne4G = '%s%s %s %s' % (numvoie, indrep, typvoie, libvoie)
        ligne4N = et[5]
        ligne4D = et[12]
        # code INSEE de la commune
        depcom = '%s%s' % (et[22],et[23])

        trace('%s / %s / %s' % (ligne4G, ligne4D, ligne4N))

        # géocodage BAN (ligne4 géo, déclarée ou normalisée si pas trouvé ou score insuffisant)
        ban = geocode(addok_ban, {'q': ligne4G, 'citycode': depcom, 'limit': '1'})
        if ban is None or ban['properties']['score']<score_min and ligne4D != ligne4G:
            ban = geocode(addok_ban, {'q': ligne4N, 'citycode': depcom, 'limit': '1'})
            trace('+ ban  L4N')
        if ban is None or ban['properties']['score']<score_min and ligne4D != ligne4N:
            ban = geocode(addok_ban, {'q': ligne4D, 'citycode': depcom, 'limit': '1'})
            trace('+ ban  L4D')


        # géocodage BANO (ligne4 géo, déclarée ou normalisée si pas trouvé ou score insuffisant)
        bano = geocode(addok_bano, {'q': ligne4G, 'citycode': depcom, 'limit': '1'})
        if bano is None or bano['properties']['score']<score_min and ligne4D != ligne4G:
            bano = geocode(addok_bano, {'q': ligne4N, 'citycode': depcom, 'limit': '1'})
            trace('+ bano L4N')
        if bano is None or bano['properties']['score']<score_min and ligne4D != ligne4N:
            bano = geocode(addok_bano, {'q': ligne4D, 'citycode': depcom, 'limit': '1'})
            trace('+ bano L4D')

        if ban is not None:
            ban_score = ban['properties']['score']
            ban_type = ban['properties']['type']
            if ['village','town','city'].count(ban_type)>0:
                ban_type = 'municipality'
        else:
            ban_score = 0
            ban_type = ''
        if bano is not None:
            bano_score = bano['properties']['score']
            if bano['properties']['type'] == 'place':
                bano['properties']['type'] = 'locality'
            bano['properties']['id'] = 'BANO_'+bano['properties']['id']
            if bano['properties']['type'] == 'housenumber':
                bano['properties']['id'] = '%s_%s' % (bano['properties']['id'],bano['properties']['housenumber'])
            bano_type = bano['properties']['type']
            if ['village','town','city'].count(bano_type)>0:
                bano_type = 'municipality'
        else:
            bano_score = 0
            bano_type = ''

        # choix de la source
        source = None

        # on a un numéro... on cherche dessus
        if numvoie != '' :
            # numéro trouvé dans les deux bases, on prend BAN sauf si score inférieur de 20% à BANO
            if ban_type == 'housenumber' and bano_type == 'housenumber' and ban_score > score_min and ban_score >= bano_score/1.2:
                source = ban
            elif ban_type == 'housenumber' and ban_score > score_min:
                source = ban
            elif bano_type == 'housenumber' and bano_score > score_min:
                source = bano
            # on cherche une interpollation dans BAN
            elif ban is None or ban_type == 'street' and int(numvoie)>2:
                ban_avant = geocode(addok_ban, {'q': '%s %s %s' % (int(numvoie)-2, typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
                ban_apres = geocode(addok_ban, {'q': '%s %s %s' % (int(numvoie)+2, typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
                if ban_avant is not None and ban_apres is not None:
                    if ban_avant['properties']['type'] == 'housenumber' and ban_apres['properties']['type'] == 'housenumber' and ban_avant['properties']['score']>0.5 and ban_apres['properties']['score']>score_min :
                        source = ban_avant
                        source['geometry']['coordinates'][0] = round((ban_avant['geometry']['coordinates'][0]+ban_apres['geometry']['coordinates'][0])/2,6)
                        source['geometry']['coordinates'][1] = round((ban_avant['geometry']['coordinates'][1]+ban_apres['geometry']['coordinates'][1])/2,6)
                        source['properties']['score'] = (ban_avant['properties']['score']+ban_apres['properties']['score'])/2
                        source['properties']['type'] = 'interpolation'
                        source['properties']['id'] = ''
                        if 'street' in source['properties']:
                            source['properties']['label'] = '%s %s %s %s' % (numvoie, source['properties']['street'], source['properties']['postcode'], source['properties']['city'])
                        else:
                            source['properties']['label'] = '%s %s %s %s' % (numvoie, source['properties']['locality'], source['properties']['postcode'], source['properties']['city'])

        # on essaye sans l'indice de répétition (BIS, TER qui ne correspond pas ou qui manque en base)
        if source is None and ban is None and indrep != '':
            trace('supp. indrep BAN : %s %s %s' % (numvoie, typvoie, libvoie))
            addok = geocode(addok_ban, {'q': '%s %s %s' % (numvoie, typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
            if addok is not None and addok['properties']['type'] == 'housenumber' and addok['properties']['score'] > score_min:
                addok['properties']['type'] = 'interpolation'
                source = addok
                trace('+ ban  L4G-indrep')
        if source is None and bano is None and indrep != '':
            trace('supp. indrep BANO: %s %s %s' % (numvoie, typvoie, libvoie))
            addok = geocode(addok_bano, {'q': '%s %s %s' % (numvoie, typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
            if addok is not None and addok['properties']['type'] == 'housenumber' and addok['properties']['score'] > score_min:
                addok['properties']['type'] = 'interpolation'
                source = addok
                trace('+ bano L4G-indrep')

        # pas trouvé ? on cherche une rue
        if source is None and typvoie != '':
            if ban_type == 'street' and bano_type == 'street' and ban_score > score_min and ban_score >= bano_score/1.2:
                source = ban
            elif ban_type == 'street' and ban_score > score_min:
                source = ban
            elif bano_type == 'street' and bano_score > score_min:
                source = bano

        # pas trouvé ? on cherche sans numvoie
        if source is None and numvoie != '':
            trace('supp. numvoie : %s %s %s' % (numvoie, typvoie, libvoie))
            addok = geocode(addok_ban, {'q': '%s %s' % (typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
            if addok is not None and addok['properties']['type'] == 'street' and addok['properties']['score'] > score_min:
                source = addok
                trace('+ ban  L4G-numvoie')
        if source is None and numvoie != '':
            addok = geocode(addok_bano, {'q': '%s %s' % (typvoie, libvoie), 'citycode': depcom, 'limit': '1'})
            if addok is not None and addok['properties']['type'] == 'street' and addok['properties']['score'] > score_min:
                source = addok
                trace('+ bano L4G-numvoie')


        # pas trouvé ? tout type accepté...
        if source is None:
            if ban_score > score_min and ban_score >= bano_score*0.8:
                source = ban
            elif ban_score > score_min:
                source = ban
            elif bano_score > score_min:
                source = bano

        if source is None:
            # attention latitude et longitude sont inversées dans le fichier CSV et donc la base sqlite
            try:
                i = commune_insee.index(depcom)
                sirene_geo.writerow(et+[commune_longitude[i],commune_latitude[i],0,'municipality','',commune_insee[i]])
                if ligne4G.strip() !='':
                    print('(%s) %s' % (depcom, ligne4G.strip()))
                    if typvoie == '' and (libvoie == 'MAIRIE' or libvoie == 'HOTEL DE VILLE'):
                        stats['townhall']+=1
                        ok = ok +1
                    else:
                        stats['municipality']+=1
                else:
                    stats['vide']+=1
                    ok = ok +1
            except:
                sirene_geo.writerow(et+['','',0,'','',''])
        else:
            ok = ok +1
            if ['village','town','city'].count(source['properties']['type'])>0:
                source['properties']['type'] = 'municipality'
            stats[source['properties']['type']]+=1
            sirene_geo.writerow(et+[source['geometry']['coordinates'][0],
                                    source['geometry']['coordinates'][1],
                                    round(source['properties']['score'],2),
                                    source['properties']['type'],
                                    source['properties']['label'],
                                    source['properties']['id']])
        if total % 1000 == 0:
            print(total, round(100*ok/total,2), stats)

print(stats)
