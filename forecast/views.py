from django.http import JsonResponse, HttpResponseBadRequest
import datetime
import requests
import re
import statistics
import xarray as xr

# --- NASA GES DISC OPeNDAP Data Fetching (GPM IMERG) ---
def get_gpm_imerg_data(lat, lon, target_date):
    """
    Fetches high-resolution precipitation data from the GPM IMERG dataset.
    """
    if target_date < datetime.datetime(2000, 6, 1):
        return None

    base_url = "https://gpm1.gesdisc.eosdis.nasa.gov/opendap/GPM_L3/GPM_3IMERGD.06"
    url_path = f"{base_url}/{target_date.year}/{target_date.strftime('%j')}"
    filename = f"3B-DAY.MS.MRG.3IMERG.{target_date.strftime('%Y%m%d')}-S000000-E235959.V06.nc4"
    url = f"{url_path}/{filename}"
    
    print(f"Attempting to fetch GPM IMERG data from URL: {url}")
    
    try:
        ds = xr.open_dataset(url)
        precip_data = ds['precipitation'].sel(lon=lon, lat=lat, method='nearest')
        precip_value = precip_data.values.item()
        return precip_value if precip_value >= 0 else 0
    except Exception as e:
        print(f"Could not fetch GPM IMERG data for {target_date.strftime('%Y-%m-%d')}. Error: {e}")
        return None

# --- NASA POWER API Data Fetching ---
def get_nasa_power_data(lat, lon, start_date, end_date):
    """
    Fetches historical weather data from the NASA POWER API.
    """
    api_url = "https://power.larc.nasa.gov/api/temporal/daily/point"
    params = {
        "start": start_date, "end": end_date, "latitude": lat, "longitude": lon, "community": "RE",
        "parameters": "PRECTOTCORR,T2M,T2M_MAX,RH2M,WS10M_RANGE",
        "format": "JSON", "header": "true", "time-standard": "LST"
    }
    try:
        response = requests.get(api_url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching NASA POWER data: {e}")
        return None

# --- Main Prediction Logic (Django View) ---
def predict_weather(request):
    location_str = request.GET.get('location')
    date_str = request.GET.get('date')

    if not location_str or not date_str:
        return HttpResponseBadRequest("Location and date are required")

    coords = re.findall(r'-?\d+\.\d+', location_str)
    if len(coords) < 2:
        return HttpResponseBadRequest("Invalid location format. Please use the map.")
    lat, lon = float(coords[0]), float(coords[1])

    try:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return HttpResponseBadRequest("Invalid date format.")

    historical_precip, successful_years = [], []
    historical_max_temps, historical_avg_temps, historical_humidities, historical_winds = [], [], [], []
    
    current_year = datetime.datetime.now().year
    years_to_fetch = list(range(current_year - 20, current_year))
    
    for year in years_to_fetch:
        historical_date = target_date.replace(year=year)
        
        precip_val = get_gpm_imerg_data(lat, lon, historical_date)
        
        date_param = f"{year}{target_date.strftime('%m%d')}"
        power_data = get_nasa_power_data(lat, lon, date_param, date_param)

        if precip_val is None and power_data and "PRECTOTCORR" in power_data["properties"]["parameter"]:
            print(f"GPM IMERG failed for {year}. Falling back to POWER API for precipitation.")
            precip_val = power_data["properties"]["parameter"]["PRECTOTCORR"].get(date_param, -999)
            if precip_val < 0: precip_val = None

        if precip_val is not None and power_data and "T2M" in power_data["properties"]["parameter"]:
            avg_temp = power_data["properties"]["parameter"]["T2M"].get(date_param, -999)
            if avg_temp > -999:
                historical_precip.append(precip_val)
                historical_max_temps.append(power_data["properties"]["parameter"]["T2M_MAX"].get(date_param, -999))
                historical_avg_temps.append(avg_temp)
                historical_humidities.append(power_data["properties"]["parameter"]["RH2M"].get(date_param, -999))
                historical_winds.append(power_data["properties"]["parameter"]["WS10M_RANGE"].get(date_param, -999))
                successful_years.append(year)

    if len(successful_years) < 5:
        return JsonResponse({"error": "Could not retrieve sufficient historical data."}, status=500)

    rainy_days = sum(1 for p in historical_precip if p > 1.0)
    rain_chance = round((rainy_days / len(historical_precip)) * 100) if historical_precip else 0
    snowy_days = sum(1 for p, t in zip(historical_precip, historical_avg_temps) if p > 1.0 and t <= 1.0)
    snow_chance = round((snowy_days / len(historical_avg_temps)) * 100) if historical_avg_temps else 0

    prediction = {
        'rainChance': rain_chance,
        'snowChance': snow_chance,
        'heatIndexC': round(statistics.mean(historical_max_temps), 1),
        'humidity': round(statistics.mean(historical_humidities), 1),
        'windSpeedKmh': round(statistics.mean(historical_winds) * 3.6, 1),
    }

    historical_data_for_chart = [
        {
            'year': y, 
            'precipitation_mm': p,
            'max_temp_c': t,
            'humidity_percent': h,
            'wind_speed_kmh': round(w * 3.6, 1),
            'is_snow_day': p > 1.0 and at <= 1.0
        } for y, p, t, h, w, at in zip(successful_years, historical_precip, historical_max_temps, historical_humidities, historical_winds, historical_avg_temps)
    ]

    response_data = {
        'location': f"Lat: {lat}, Lon: {lon}",
        'date': date_str, 
        'prediction': prediction, 
        'historicalData': historical_data_for_chart
    }
    return JsonResponse(response_data)

