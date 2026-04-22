import lxml.etree as ET

tree = ET.parse(r'data\easa\7AD833_2026-03-13_10.13.51_EAR-for-Aerodromes-Regulation-EU-No-139-2014.xml')
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
sdts = tree.xpath('.//w:sdt[w:sdtPr/w:id[@w:val="-1513584453"]]', namespaces=ns)

if sdts:
    sdt = sdts[0]
    text = "".join(sdt.itertext())
    print("Found text:", text[:500])
else:
    print("w:sdt not found!")
