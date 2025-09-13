"""
Timezone utilities for Colombian timezone handling
"""
import pandas as pd
import pytz
from datetime import datetime

# Define Colombian timezone
COLOMBIA_TZ = pytz.timezone('America/Bogota')

def convert_to_colombia_time(df):
    """Convert UTC timestamps to Colombian timezone"""
    if '_time' in df.columns:
        # Ensure the datetime column is timezone-aware
        if df['_time'].dt.tz is None:
            # If no timezone info, assume UTC
            df['_time'] = df['_time'].dt.tz_localize('UTC')
        
        # Convert to Colombian timezone
        df['_time'] = df['_time'].dt.tz_convert(COLOMBIA_TZ)
    return df

def format_colombia_time(timestamp):
    """Format timestamp in Colombian timezone"""
    if timestamp.tz is None:
        # If no timezone info, assume UTC
        timestamp = pytz.utc.localize(timestamp)
    
    # Convert to Colombian timezone
    colombia_time = timestamp.astimezone(COLOMBIA_TZ)
    return colombia_time.strftime("%Y-%m-%d %H:%M:%S COT")

def get_current_colombia_time():
    """Get current time in Colombian timezone"""
    utc_now = pytz.utc.localize(utc_now)
    colombia_now = utc_now.astimezone(COLOMBIA_TZ)
    return colombia_now

def colombia_time_to_string(timestamp=None):
    """Convert Colombian time to formatted string"""
    if timestamp is None:
        timestamp = get_current_colombia_time()
    return timestamp.strftime("%Y-%m-%d %H:%M:%S COT")