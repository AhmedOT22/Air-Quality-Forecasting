# Air Quality Forecasting in Toronto Downtown (2020–2024)

## Overview

This project aims to forecast the Air Quality Index (AQI) in Toronto Downtown using historical data of climate factors and pollutant particles between 2020 and 2024. The main goal is to model AQI behavior and provide accurate short-term predictions that can help the public and policymakers respond proactively to pollution risks.

---

## Problem Statement

Urban air quality affects public health, environmental sustainability, and economic productivity. The challenge is to forecast AQI effectively using available environmental data, while accounting for data limitations and non-linear relationships between pollutants and AQI levels.

---

## Objectives

- Calculate AQI based on pollutant concentrations using EPA-defined formulas.
- Identify which pollutant contributes most to AQI each day.
- Compare classical and machine learning forecasting models.
- Perform 7-day recursive AQI forecasting using the best-performing model.

---

## Dataset

The project integrates multiple real-world sources:
- **Climate data**: temperature, precipitation, heating/cooling degree days
- **Pollutant data**: PM2.5, SO₂, NO₂, NO, NOₓ, O₃ (hourly data aggregated daily)

Data range: **January 2020 – December 2024**

---

## Methodology

1. **Data Cleaning**:
   - Replaced invalid values (e.g. `9999`, `-999`) with `NaN`
   - Used median/mean imputation after visualizing outliers

2. **Data Integration**:
   - Merged pollutant and climate datasets
   - Standardized date formats and handled missing timestamps

3. **AQI Calculation**:
   - Computed AQI for PM2.5, SO₂, NO₂, and O₃ using EPA breakpoints
   - Used the max AQI per row to determine final AQI and dominant pollutant

4. **Feature Engineering**:
   - Created lag variables for AQI
   - Removed highly correlated variables to reduce redundancy
   - Added climate-based predictors

5. **Model Selection**:
   - Benchmarked ARIMA, SARIMA, ETS, Prophet, Linear Regression, Random Forest, and XGBoost
   - Evaluated using MSE, MAE, and R²

6. **Final Model**:
   - Random Forest chosen for final forecasting based on high accuracy and speed

7. **Forecasting**:
   - Performed 7-day recursive AQI predictions using fine-tuned Random Forest

---

## Results

| Model            | RMSE   | R² Score |
|------------------|--------|----------|
| Random Forest    | 7.59   | 0.97     |
| XGBoost          | 8.63   | 0.96     |
| Linear Regression| ~14.0  | ~0.70    |
| ARIMA/SARIMA     | ~12.0  | < 0.05   |
| ETS / Prophet    | ~13.5+ | < 0.10   |

---

## Challenges

- Unavailable CO and PM10 data
- Raw data with missing or corrupt values
- Strong collinearity among NO, NO₂, NOₓ, and SO₂
- Forecast degradation during recursive steps

---

## Requirements

- Python 3.9+
- Libraries: `pandas`, `numpy`, `scikit-learn`, `statsmodels`, `xgboost`, `prophet`, `matplotlib`, `seaborn`

Install via:
```bash
pip install -r requirements.txt
```

## Usage
To run the project:

1. Clone the repository

2. Run the notebook: AirQuality.ipynb

3. Adjust model or forecast horizon as needed

## Author
Ahmed Ouazzani - <a href="https://github.com/AhmedOT22" target="_blank">GitHub Profile</a>

## License
MIT License – see LICENSE for details.

