# Define AQI Calculation for Each Pollutant
def calculate_pm25_aqi(pm25):
    """ Calculate AQI for PM2.5 """
    if pm25 <= 12: return (50/12) * pm25
    elif pm25 <= 35.4: return (100-51)/(35.4-12.1) * (pm25-12.1) + 51
    elif pm25 <= 55.4: return (150-101)/(55.4-35.5) * (pm25-35.5) + 101
    elif pm25 <= 150.4: return (200-151)/(150.4-55.5) * (pm25-55.5) + 151
    elif pm25 <= 250.4: return (300-201)/(250.4-150.5) * (pm25-150.5) + 201
    else: return (500-301)/(500-250.5) * (pm25-250.5) + 301

def calculate_so2_aqi(so2):
    """ Calculate AQI for SO2 """
    if so2 <= 35: return (50/35) * so2
    elif so2 <= 75: return (100-51)/(75-36) * (so2-36) + 51
    elif so2 <= 185: return (150-101)/(185-76) * (so2-76) + 101
    elif so2 <= 304: return (200-151)/(304-186) * (so2-186) + 151
    elif so2 <= 604: return (300-201)/(604-305) * (so2-305) + 201
    else: return (500-301)/(1004-605) * (so2-605) + 301

def calculate_no2_aqi(no2):
    """ Calculate AQI for NO2 """
    if no2 <= 53: return (50/53) * no2
    elif no2 <= 100: return (100-51)/(100-54) * (no2-54) + 51
    elif no2 <= 360: return (150-101)/(360-101) * (no2-101) + 101
    elif no2 <= 649: return (200-151)/(649-361) * (no2-361) + 151
    elif no2 <= 1249: return (300-201)/(1249-650) * (no2-650) + 201
    else: return (500-301)/(2049-1250) * (no2-1250) + 301

def calculate_o3_aqi(o3):
    """ Calculate AQI for O3 """
    if o3 <= 54: return (50/54) * o3
    elif o3 <= 70: return (100-51)/(70-55) * (o3-55) + 51
    elif o3 <= 85: return (150-101)/(85-71) * (o3-71) + 101
    elif o3 <= 105: return (200-151)/(105-86) * (o3-86) + 151
    elif o3 <= 200: return (300-201)/(200-106) * (o3-106) + 201
    else: return (500-301)/(405-201) * (o3-201) + 301