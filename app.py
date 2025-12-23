import json
import random
from datetime import datetime
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from io import BytesIO

# --- IMPORTANT: REGIONAL FACTORS FOR DYNAMIC RESULTS (UPDATED) ---
# Added 'base_paddy_coverage' to ensure Land Cover Distribution varies by region.
REGIONAL_FACTORS = {
    "eastern_up": {
        "base_yield_avg": 4.0, 
        "yield_multiplier": 2.0,
        "base_water_risk": 50,
        "base_accuracy": 75,
        "base_paddy_coverage": 40 # Region-specific base for Paddy
    },
    "tamil_nadu": {
        "base_yield_avg": 5.5, 
        "yield_multiplier": 1.5,
        "base_water_risk": 30,
        "base_accuracy": 80,
        "base_paddy_coverage": 55 # Region-specific base for Paddy
    },
    "punjab": {
        "base_yield_avg": 6.8, 
        "yield_multiplier": 3.0,
        "base_water_risk": 15,
        "base_accuracy": 90,
        "base_paddy_coverage": 70 # Region-specific base for Paddy
    },
    "west_bengal": {
        "base_yield_avg": 4.5, 
        "yield_multiplier": 2.5,
        "base_water_risk": 40,
        "base_accuracy": 78,
        "base_paddy_coverage": 50 # Region-specific base for Paddy
    },
    # Default fallback for custom drawn area
    "default": { 
        "base_yield_avg": 5.0, 
        "yield_multiplier": 2.0,
        "base_water_risk": 35,
        "base_accuracy": 82,
        "base_paddy_coverage": 45 # Default base for Paddy
    }
}

# --------------------
# FLASK APP SETUP
# --------------------
app = Flask(__name__)
# Enable CORS to allow the frontend HTML file (running on a different port/origin) to talk to the server
CORS(app) 


def _calculate_dynamic_metrics(date_start_str, date_end_str, study_area_key):
    """
    Simulates GEE analysis by calculating dynamic metrics based on the date range AND region.
    """
    
    # 1. Get Regional Base Factors
    factors = REGIONAL_FACTORS.get(study_area_key, REGIONAL_FACTORS['default'])
    
    try:
        start = datetime.strptime(date_start_str, '%Y-%m-%d')
        end = datetime.strptime(date_end_str, '%Y-%m-%d')
    except ValueError:
        raise ValueError("Invalid date format.")

    diff_time = abs(end - start)
    diff_days = diff_time.days
    
    # Define optimal season length for rice (roughly 135 days)
    optimal_season_days = 135
    max_deviation = 60 
    deviation = abs(diff_days - optimal_season_days)
    
    # Dynamic factor peaks at 1.0 when diff_days is near 135, and drops off otherwise
    dynamic_factor = max(0, 1 - deviation / max_deviation) 
    
    # Generate a unique seed for small random variation, tied to the dates
    random.seed(diff_days + start.day + end.day) 
    date_seed = random.uniform(0.9, 1.1)

    # --- 1. CLASSIFICATION METRICS ---
    # Accuracy is based on regional base + dynamic factor (longer/better season = higher accuracy)
    accuracy = factors["base_accuracy"] + (dynamic_factor * 10 * random.uniform(0.8, 1.2))
    accuracy = min(95, accuracy) # Cap at 95%
    
    # --- 2. YIELD ESTIMATION ---
    # Yield is based on regional average + dynamic factor * multiplier
    yield_estimate = factors["base_yield_avg"] + (dynamic_factor * factors["yield_multiplier"] * date_seed)
    
    # --- 3. PHENOLOGY (Growth Stage) and NDVI Curve ---
    
    # Determine stage based on elapsed days (phenology)
    if diff_days < 50:
        stage = "Transplanting/Vegetative (Early)"
        # Curve starts low, peaks later
        ndvi_data = [0.3, 0.45, 0.6, 0.7 + date_seed * 0.1, 0.72 + date_seed * 0.05]
    elif diff_days < 100:
        stage = "Active Tillering/Panicle Initiation (Peak)"
        # Curve is near its highest point
        ndvi_data = [0.4, 0.65, 0.85 + date_seed * 0.05, 0.8 + date_seed * 0.04, 0.7 - date_seed * 0.02]
    elif diff_days < 130:
        stage = "Flowering/Grain Filling (Late)"
        # Curve is falling slightly
        ndvi_data = [0.75 + date_seed * 0.05, 0.65, 0.5, 0.45, 0.4 - date_seed * 0.05]
    else:
        stage = "Ripening/Harvesting (End)"
        # Curve is low, indicating senescence
        ndvi_data = [0.7, 0.5, 0.4, 0.35, 0.3 - date_seed * 0.02]

    # --- 4. HEALTH & WATER ---
    
    health_risk = factors["base_water_risk"] + ((1 - dynamic_factor) * 40)
    health_risk = min(80, health_risk) 

    if dynamic_factor < 0.6:
        risk_value = "High Stress"
        recommendation = "Severe stress detected. Immediate water and nutrient assessment needed."
    elif dynamic_factor < 0.85:
        risk_value = "Moderate Stress"
        recommendation = "Monitor water levels closely. Consider supplemental irrigation."
    else:
        risk_value = "Low Stress"
        recommendation = "Optimal growth confirmed. Maintain current standing water."
        
    # --- 5. LAND COVER ESTIMATION (CORRECTED) ---
    paddy_base = factors.get("base_paddy_coverage", 45) # Use regional base coverage
    water_base = 20 
    urban_base = 10
    # Adjust Fallow base to ensure P + W + U + F base sum to 100
    fallow_base_new = 100 - paddy_base - water_base - urban_base 
    
    land_cover_data = [
        paddy_base + (dynamic_factor * 15),     # Paddy: Uses regional base + seasonal boost
        water_base - (dynamic_factor * 5),      # Water: Decreases with seasonal quality
        urban_base,                             # Urban: Constant
        fallow_base_new - (dynamic_factor * 10) # Fallow: Uses adjusted base + seasonal drop
    ]


    return {
        "accuracy": f"{accuracy:.1f}",
        "kappa": f"{accuracy * 0.01 * 0.85:.2f}",
        "precision": f"{accuracy * 0.01 * 0.9:.2f}",
        "recall": f"{accuracy * 0.01 * 0.88:.2f}",
        "f1score": f"{accuracy * 0.01 * 0.89:.2f}",
        "landCover": [round(n, 2) for n in land_cover_data], # Use the corrected data
        "ndvi": [round(n, 2) for n in ndvi_data],
        "yield": {
            "estimate": yield_estimate,
            "range": [yield_estimate * 0.9, yield_estimate * 1.1],
            "regionalAvg": factors["base_yield_avg"],
            "stage": stage
        },
        "health": {
            "riskLevel": round(health_risk),
            "riskValue": risk_value
        },
        "water": {
            "recommendation": recommendation,
            "etRate": f"{4.0 + (date_seed * 1.5):.2f}",
            "soilMoisture": [round(random.uniform(0.5, 0.7), 2) for _ in range(7)],
        }
    }


@app.route('/run_analysis', methods=['POST'])
def run_analysis():
    """
    Primary API endpoint to run the geospatial analysis based on frontend parameters.
    """
    data = request.json
    
    required_fields = ['dateStart', 'dateEnd', 'studyArea', 'model']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required analysis parameters."}), 400

    try:
        # Pass the studyArea key to the calculation function
        results = _calculate_dynamic_metrics(data['dateStart'], data['dateEnd'], data['studyArea'])
        
        return jsonify(results)
    
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Analysis failed: {e}")
        return jsonify({"error": "Internal server error during analysis."}), 500


def _generate_text_report(params):
    """Generates a plain text report from the results and parameters."""
    results = params.get('results', {})
    yield_data = results.get('yield', {})
    health_data = results.get('health', {})
    water_data = results.get('water', {})
    
    # Format land cover distribution
    land_cover_vals = results.get('landCover', [0, 0, 0, 0])
    land_cover_labels = ['Paddy', 'Water', 'Urban', 'Fallow Land']
    land_cover_str = ', '.join([f"{label}: {val:.2f}%" for label, val in zip(land_cover_labels, land_cover_vals)])

    report = f"""
PaddyTrack Report
==================================================
Date of Analysis: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

--- 1. Analysis Parameters ---
Area of Interest (AOI): {params.get('aoi', 'N/A')}
Date Range:             {params.get('startDate', 'N/A')} to {params.get('endDate', 'N/A')}
Satellite Source:       {params.get('satellite', 'N/A')}
Classification Model:   {params.get('model', 'N/A')}

--- 2. Classification Metrics ---
Accuracy:     {results.get('accuracy', '--')}%
Kappa Score:  {results.get('kappa', '--')}
Precision:    {results.get('precision', '--')}
Recall:       {results.get('recall', '--')}
F1-Score:     {results.get('f1score', '--')}

--- 3. Land Cover Distribution ---
Distribution: {land_cover_str}

--- 4. Yield Estimation ---
Estimated Yield: {yield_data.get('estimate', 0):.2f} t/ha
Potential Range: {yield_data.get('range', [0, 0])[0]:.2f} - {yield_data.get('range', [0, 0])[1]:.2f} t/ha
Regional Average: {yield_data.get('regionalAvg', 0):.2f} t/ha
Growth Stage:    {yield_data.get('stage', 'N/A')}

--- 5. Crop Health & Water Management ---
Pest & Disease Risk: {health_data.get('riskLevel', 0)}% ({health_data.get('riskValue', 'N/A')})
Water Recommendation: {water_data.get('recommendation', 'N/A')}
ET Rate (Avg):       {water_data.get('etRate', '--')} mm/day

==================================================
"""
    return report.strip()


@app.route('/download_report', methods=['POST'])
def download_report():
    """
    Endpoint to generate and return a TXT report file.
    """
    data = request.json
    
    report_content = _generate_text_report(data)
    
    buffer = BytesIO(report_content.encode('utf-8'))
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='text/plain',
        as_attachment=True,
        download_name='PaddyTrack_Report.txt'
    )


if __name__ == '__main__':
    print("-------------------------------------------------------")
    print("PaddyTrack Backend Server starting...")
    print("To run the frontend, open 'crop paddy/index.html' in your browser.")
    print("-------------------------------------------------------")
    app.run(host='127.0.0.1', port=5000, debug=True)