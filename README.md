# Multimodal Accessibility Analysis in Salzburg

This repository contains the Python scripts used for the GIS-based multimodal accessibility analysis conducted as part of a Master's thesis at the University of Salzburg in 2026.

The study compares accessibility by **private car, bus and Park & Ride (P&R)** in the Flachgau region of Salzburg. Accessibility is evaluated using three main indicators:

- travel time
- travel costs
- CO₂ emissions

The analysis considers several temporal scenarios and destinations in and around the city of Salzburg.

## Study Area and Scenarios

The analysis focuses on residential addresses in the Flachgau region and accessibility to five selected destinations:

- Salzburg Main Station
- Salzburg Airport
- Paris Lodron University Salzburg
- SALK
- Europark Salzburg

Six temporal scenarios were analysed:

- Monday morning
- Monday afternoon
- Friday morning
- Friday afternoon
- Saturday morning
- Saturday afternoon

The final comparison is based on 70,935 residential origins.

## Repository Structure

```text
scripts/
│
├── Appendix_B_Address_Data_Cleaning.py
├── Appendix_C_Street_Network_Cleaning.py
├── Appendix_D_EVIS_Integration.py
├── Appendix_E_Travel_Mode_Definition.py
└── Appendix_F_Result_Table_Generation.py
