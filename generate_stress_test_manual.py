import os
from fpdf import FPDF

def generate_stress_manual(filename: str = "OM_A_Stress_Test.pdf"):
    print(f"Generating voluminous stress test manual: {filename}...")
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- PAGE 1: Front Matter ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 24)
    pdf.cell(0, 50, "OPERATIONS MANUAL - PART A", ln=True, align='C')
    pdf.set_font("Arial", 'I', 12)
    pdf.cell(0, 10, "STRESS TEST MASTER - REVISION 2026.1", ln=True, align='C')
    pdf.ln(30)
    
    # --- PAGE 2: SMS & Org ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "SECTION 1: ORGANISATION AND MANAGEMENT", ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 7, "The airline management system is integrated across all departments. The Accountable Manager (AM) has full authority over financial and human resources. The Safety Manager reports directly to the AM. " * 20)
    
    # --- PAGE 3-5: FTL (The "Context Splitting" Test) ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "SECTION 4: FLIGHT AND DUTY TIME LIMITATIONS (FTL)", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, "4.1 General Principles", ln=True)
    pdf.set_font("Arial", '', 11)
    # Dense text spanning across page boundaries
    FTL_TEXT = """In accordance with ORO.FTL.210, the operator has established a fatigue risk management system. 
    The maximum basic daily FDP shall be 13 hours. This FDP shall be reduced by 30 minutes for every sector from the third sector onwards, 
    with a maximum total reduction of 2 hours. When the FDP starts in the WOCL (Window of Circadian Low), the maximum FDP is further reduced 
    as specified in the tables below.
    
    Rest periods are calculated based on the previous duty period. The minimum rest period provided before a flight duty period starting at home base 
    shall be at least as long as the preceding duty period, or 12 hours, whichever is greater. 
    """
    pdf.multi_cell(0, 7, FTL_TEXT * 15) # Force multiple pages
    
    # --- PAGE 6: Fuel Policy (The "Table & Data" Test) ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "SECTION 3: FUEL POLICY", ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 7, "The fuel policy is based on EASA CAT.OP.MPA.150. The commander shall ensure that the amount of usable fuel on board is sufficient to complete the planned flight safely. " * 5)
    
    # Fuel Table
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(40, 10, "Fuel Component", 1)
    pdf.cell(100, 10, "Calculation Method", 1)
    pdf.cell(40, 10, "Min Requirement", 1)
    pdf.ln()
    
    pdf.set_font("Arial", '', 9)
    fuel_data = [
        ("Taxi Fuel", "Based on actual consumption at departure AD", "200 kg"),
        ("Trip Fuel", "From take-off to landing at destination", "FMC calculation"),
        ("Contingency", "5% of trip fuel or 5 mins at 1500ft", "Min 15 mins"),
        ("Alternate", "From missed approach to alternate landing", "Standard profile"),
        ("Final Reserve", "45 mins for piston / 30 mins for jet", "At 1500ft AGL")
    ]
    for comp, method, req in fuel_data:
        pdf.cell(40, 10, comp, 1)
        pdf.cell(100, 10, method, 1)
        pdf.cell(40, 10, req, 1)
        pdf.ln()

    # --- PAGE 7: Noise/Irrelevant Content ---
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "SECTION 9: CATERING AND CABIN SERVICE", ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 7, "This section describes the menu selection and galley loading procedures. " * 50)
    
    pdf.output(filename)
    print(f"Successfully generated {filename}")

if __name__ == "__main__":
    generate_stress_manual()
