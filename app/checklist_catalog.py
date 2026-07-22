"""50a (MONTHLY) and 50b (QUARTERLY) Preventive-Maintenance checklist form structure.

GENERATED from the app's ChecklistCatalog.kt — keep in sync if the paper form changes.
Shape: [ {section, equipment: [ {sr_no, equipment, checkpoints[]} ]} ].
Used to (a) pre-seed a full-form checklist document as UNSET cells, and (b) know each
equipment row's checkpoints when a machine's PM is QC-closed.
"""

# form_type -> doc_no. W-202 uses two forms (50a monthly, 50b quarterly); A-185 uses one
# combined form (F.41). Keeping A-185 on its own form_type keeps the two plants separate.
DOC_NO = {"MONTHLY": "CFPLA.C4.F.50a", "QUARTERLY": "CFPLA.C4.F.50b", "A185": "CFPLB.C4.F.41"}

AFTER_MAINTENANCE = ['Cleanliness of machine/ Tools box', 'All tools are in tool box', 'No nuts, Bolts and any spare parts on floor', 'No grease or oil left over']

CATALOG_50A = [
    {
        "section": 'Lower Basement',
        "equipment": [
            {"sr_no": 1, "equipment": 'Lift 1 Old', "checkpoints": ['Electrical connections', 'Doors', 'Switches']},
            {"sr_no": 2, "equipment": 'Lift 3 - Hydraulic', "checkpoints": ['Electrical connections', 'Switches', 'Doors']},
            {"sr_no": 3, "equipment": 'L-sealer - Manual', "checkpoints": ['Sealer & cutting Knife intactness']},
            {"sr_no": 4, "equipment": 'Auto L-sealer (shrink wrapper)', "checkpoints": ['sealer intactness', 'Heater (coil)', 'Pressure and leakage', 'Cutting knife check', 'Pannel knobs/ display']},
            {"sr_no": 5, "equipment": 'Shrink Wrap - Web sealer', "checkpoints": ['sealer intactness', 'Heater (coil)', 'Pressure and leakage', 'Cutting knife check', 'Pannel knobs/ display']},
            {"sr_no": 6, "equipment": 'Pet Sealer', "checkpoints": ['Motor', 'Electric connection', 'sealing check', 'oiling / greasing', 'conveyor belt intactness']},
            {"sr_no": 7, "equipment": 'CUP Sealer-1', "checkpoints": ['sealer intactness']},
            {"sr_no": 8, "equipment": 'CUP Sealer-2', "checkpoints": ['sealer intactness']},
            {"sr_no": 9, "equipment": 'Band Sealer', "checkpoints": ['Sealer', 'Conveyor Intactness', 'Airline / Nitrogen Pressure', 'leakage']},
            {"sr_no": 10, "equipment": 'Hand Wash station', "checkpoints": ['Blower & Dispenser', 'water connections']},
            {"sr_no": 11, "equipment": 'Air Curtain', "checkpoints": ['Fan Blower']},
        ],
    },
    {
        "section": 'Upper Basement Floor',
        "equipment": [
            {"sr_no": 12, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oiling/Greasing of bearings']},
            {"sr_no": 13, "equipment": 'Hand Wash station', "checkpoints": ['Blower & Dispenser', 'water connections']},
        ],
    },
    {
        "section": 'Service Floor',
        "equipment": [
            {"sr_no": 14, "equipment": 'Compress Air Dryer', "checkpoints": ['Filter', 'Oiling/Greasing', 'Valve']},
            {"sr_no": 15, "equipment": 'Disel Generator', "checkpoints": ['Oiling/Greasing', 'Valve']},
        ],
    },
    {
        "section": 'First Floor',
        "equipment": [
            {"sr_no": 16, "equipment": 'Band Sealer', "checkpoints": ['Sealer', 'Conveyor Intactness', 'Heater', 'Airline / Nitrogen Pressure']},
            {"sr_no": 17, "equipment": 'Air Curtain', "checkpoints": ['Fan Blower']},
            {"sr_no": 18, "equipment": 'FFS -ARM', "checkpoints": ['bucket intactness and intregrity', 'Intactness of colller', 'Sealer and knife', 'compessed air pressure', 'Nitrogen air pressure', 'oiling / greasing od bearings', 'Pannel knobs']},
        ],
    },
    {
        "section": '1st Mezzanine',
        "equipment": [
            {"sr_no": 19, "equipment": 'Band Sealer', "checkpoints": ['Sealer', 'Conveyor Intactness', 'Heater', 'Airline / Nitrogen Pressure']},
            {"sr_no": 20, "equipment": 'Band Sealer', "checkpoints": ['Sealer', 'Conveyor Intactness', 'Heater', 'Airline / Nitrogen Pressure']},
            {"sr_no": 21, "equipment": 'Hand Wash station', "checkpoints": ['Blower & Dispenser']},
            {"sr_no": 22, "equipment": 'Air Curtain', "checkpoints": ['fan blower']},
        ],
    },
    {
        "section": '2nd Floor',
        "equipment": [
            {"sr_no": 23, "equipment": 'Shrink Wrap - L sealer', "checkpoints": ['sealer intactness', 'Heater (coil)', 'Pressure and leakage', 'Cutting knife check', 'Pannel knobs/ display']},
            {"sr_no": 24, "equipment": 'Foot Sealer', "checkpoints": ['sealer intactness', 'Heater (coil)']},
            {"sr_no": 25, "equipment": 'Band Sealer', "checkpoints": ['Sealer', 'Conveyor Intactness', 'Heater', 'Airline / Nitrogen Pressure']},
            {"sr_no": 26, "equipment": 'Hand Wash station', "checkpoints": ['Blower & Dispenser', 'water connections']},
            {"sr_no": 27, "equipment": 'Flow Wrap Machine', "checkpoints": ['Heater', 'Blade', 'Motor', 'Sensor', 'Oiling /Greasing', 'Printer & display', 'conveyor belt intactness']},
            {"sr_no": 28, "equipment": 'Flow Wrap Machine', "checkpoints": ['Heater', 'Blade', 'Motor', 'Sensor', 'Oiling /Greasing', 'Printer & display', 'conveyor belt intactness']},
            {"sr_no": 29, "equipment": 'Sheet & Cut Machine', "checkpoints": ['conveyor belt intactness']},
            {"sr_no": 30, "equipment": 'Almond Slicer', "checkpoints": ['Motor', 'Blades integrity']},
            {"sr_no": 31, "equipment": 'Trolleys', "checkpoints": ['oiling/greasing & wheels integrity']},
            {"sr_no": 32, "equipment": 'Kruger Machine', "checkpoints": ['conveyor belt intactness', 'Electrical connections']},
            {"sr_no": 33, "equipment": 'Chocolate Melting Tank', "checkpoints": ['Heater', 'Motor']},
            {"sr_no": 34, "equipment": 'Chocolate Enrober Tank', "checkpoints": ['Heater', 'Motor']},
            {"sr_no": 35, "equipment": 'Chocolate Cooling Machine', "checkpoints": ['Compressor -oiling/greasing', 'Motor']},
            {"sr_no": 36, "equipment": 'Chocolate Coating Pan', "checkpoints": ['Electrical connections']},
            {"sr_no": 37, "equipment": 'Chocolate Coating Pan', "checkpoints": ['Electrical connections']},
            {"sr_no": 38, "equipment": 'Chocolate Coating Pan', "checkpoints": ['Electrical connections']},
            {"sr_no": 39, "equipment": 'Tray Roaster', "checkpoints": ['Heater', 'Motor']},
        ],
    },
    {
        "section": 'Store Area',
        "equipment": [
            {"sr_no": 40, "equipment": 'Lift 2 New', "checkpoints": ['Electrical connections', 'Doors', 'Switches']},
        ],
    },
    {
        "section": 'Service Floor (Printing)',
        "equipment": [
            {"sr_no": 42, "equipment": 'Printing Machine 1', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 43, "equipment": 'Printing Machine 2', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 44, "equipment": 'Printing Machine 3', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 45, "equipment": 'Printing Machine 4', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 46, "equipment": 'Printing Machine 5', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 47, "equipment": 'Printing Machine 6', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 48, "equipment": 'Printing Machine 7', "checkpoints": ['Motor', 'belt Conveyor intactness', 'printer and display pannel', 'sensor check']},
            {"sr_no": 49, "equipment": 'Disel Generator', "checkpoints": ['filters', 'Leakage', 'Water', 'Oil Levels']},
            {"sr_no": 50, "equipment": 'Compressor Air Dryer', "checkpoints": ['Line check', 'SOV Valve', 'Compressor oil', 'Greasing and Servicing']},
        ],
    },
    {
        "section": 'External Premises',
        "equipment": [
            {"sr_no": 51, "equipment": 'Nitrogen Plant', "checkpoints": ['Check Electrical connectios', 'Generation Cycle O2 %']},
            {"sr_no": None, "equipment": 'Air Curtain (Workers entry)', "checkpoints": ['Fan Blower']},
        ],
    },
    {
        "section": 'Terrace',
        "equipment": [
            {"sr_no": 52, "equipment": 'Dicer Machine', "checkpoints": ['Blades integrity', 'motor']},
            {"sr_no": 53, "equipment": 'Tray Roaster 1', "checkpoints": ['Heater', 'Motor']},
            {"sr_no": 54, "equipment": 'Tray Roaster 1', "checkpoints": ['Heater', 'Motor']},
            {"sr_no": 55, "equipment": 'RO water purifier 200ltr/hr', "checkpoints": ['Tank integrity', 'Filter', 'motor']},
            {"sr_no": 56, "equipment": 'RO water purifier 2000ltr/hr', "checkpoints": ['Tank integrity', 'Filter', 'motor']},
            {"sr_no": 57, "equipment": 'Trolleys', "checkpoints": ['oiling/greasing & wheels integrity']},
            {"sr_no": 58, "equipment": 'Foot Sealer 1', "checkpoints": ['Sealer', 'Heater']},
            {"sr_no": 59, "equipment": 'Foot Sealer 2', "checkpoints": ['Sealer', 'Heater']},
            {"sr_no": 60, "equipment": 'Blancher', "checkpoints": ['Conveyor belt integrity', 'Rollers', 'Integrity of wire net bucket', 'Bearings and sprockets', 'Cerculation pump', 'Motar']},
            {"sr_no": 61, "equipment": 'water bath', "checkpoints": ['Heating coil', 'Temperature controller', 'Steam nozzles', 'Cerculation pump', 'motor', 'Leads and gaskets', 'Swiches']},
        ],
    },
    {
        "section": 'Miscallenous',
        "equipment": [
            {"sr_no": 62, "equipment": 'Windows and mesh', "checkpoints": []},
            {"sr_no": 63, "equipment": 'Dorrs and gaps', "checkpoints": []},
            {"sr_no": 64, "equipment": 'Pestoflash Machines', "checkpoints": []},
            {"sr_no": 65, "equipment": 'Drainage and mesh coverings', "checkpoints": []},
            {"sr_no": 66, "equipment": 'gaskets (for all machines )', "checkpoints": []},
            {"sr_no": 67, "equipment": 'Lids of all equipments (acrylic or plastics)', "checkpoints": []},
            {"sr_no": 68, "equipment": 'Purifier Water Cooler', "checkpoints": []},
            {"sr_no": 69, "equipment": 'VRV System', "checkpoints": []},
        ],
    },
]

CATALOG_50B = [
    {
        "section": 'Lower Basement',
        "equipment": [
            {"sr_no": 1, "equipment": 'Strapping Machine', "checkpoints": ['Heater', 'Motor', 'Greasing/Oil', 'Belt Intact']},
            {"sr_no": 2, "equipment": 'Borewell Pump', "checkpoints": ['Motor', 'Greasing/Oil']},
            {"sr_no": 3, "equipment": 'Inverter 1', "checkpoints": ['Electric Connections', 'Power Backup', 'Battery']},
            {"sr_no": 4, "equipment": 'Vaccum Machine -1', "checkpoints": ['Heater', 'Compress Air', 'Pipes Intactness', 'Greasing/Oil']},
        ],
    },
    {
        "section": 'Upper Basement',
        "equipment": [
            {"sr_no": 5, "equipment": 'Exhaust Fans -1/2/3/4', "checkpoints": ['Mesh/Filter', 'Motor']},
            {"sr_no": 6, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oil/greasing']},
        ],
    },
    {
        "section": 'Store',
        "equipment": [
            {"sr_no": 7, "equipment": 'Freezer', "checkpoints": ['Compressor', 'Motor']},
            {"sr_no": 8, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oil/greasing']},
        ],
    },
    {
        "section": 'Service Floor',
        "equipment": [
            {"sr_no": 9, "equipment": 'Freezer', "checkpoints": ['Compressor', 'Motor']},
            {"sr_no": 10, "equipment": 'Pan Coater', "checkpoints": ['Motor', 'Oiling/Greasing']},
            {"sr_no": 11, "equipment": 'Hot Air Oven', "checkpoints": ['Heater', 'Motor']},
            {"sr_no": 12, "equipment": 'Exhaust Fans -1/2/3/4/5', "checkpoints": ['Mesh/Filter', 'Motor']},
            {"sr_no": 13, "equipment": 'Compressor-1/2', "checkpoints": ['Motor', 'Valve', 'Compressor oil', 'Oiling/Greasing']},
        ],
    },
    {
        "section": 'Laboratory',
        "equipment": [
            {"sr_no": 14, "equipment": 'Mantle Heater', "checkpoints": ['Heat Coil']},
            {"sr_no": 15, "equipment": 'Hot - Air Oven', "checkpoints": ['Temp. meter']},
        ],
    },
    {
        "section": 'First Floor',
        "equipment": [
            {"sr_no": 16, "equipment": 'Exhaust Fans -1/2/3', "checkpoints": ['Mesh/Filter', 'Motor']},
            {"sr_no": 17, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oil/greasing']},
        ],
    },
    {
        "section": 'First Mez. Floor',
        "equipment": [
            {"sr_no": 18, "equipment": 'Vaccum Machine -2', "checkpoints": ['Heater', 'Compress Air', 'Pipes Intactness', 'Greasing/Oil']},
            {"sr_no": 19, "equipment": 'Exhaust Fans -1/2', "checkpoints": ['Mesh/Filter', 'Motor']},
            {"sr_no": 20, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oil/greasing']},
        ],
    },
    {
        "section": 'Second Floor',
        "equipment": [
            {"sr_no": 21, "equipment": 'Stabilizer', "checkpoints": ['Transformer']},
            {"sr_no": 22, "equipment": 'Exhaust Fans -1/2/3/4', "checkpoints": ['Mesh/Filter', 'Motor']},
        ],
    },
    {
        "section": 'Second Mez. Floor',
        "equipment": [
            {"sr_no": 23, "equipment": 'Freezer', "checkpoints": ['Compressor', 'Motor']},
            {"sr_no": 24, "equipment": 'Oven', "checkpoints": ['Blower', 'Dispensor']},
            {"sr_no": 25, "equipment": 'Peanut Butter Machine', "checkpoints": ['Motor']},
            {"sr_no": 26, "equipment": 'Paddle Mixer (90kgs)', "checkpoints": ['Motor', 'Blade Integrity', 'Oiling/Greasing']},
            {"sr_no": 27, "equipment": 'Paddle Mixer (60kgs)', "checkpoints": ['Motor', 'Blade Integrity', 'Oiling/Greasing']},
            {"sr_no": 28, "equipment": 'Paddle Mixer (180kgs)', "checkpoints": ['Motor', 'Blade Integrity', 'Oiling/Greasing']},
            {"sr_no": 29, "equipment": 'Pulveriser Machine', "checkpoints": ['Blade Integrity']},
            {"sr_no": 30, "equipment": 'Pan Coater -1/2', "checkpoints": ['Motor', 'Oiling/Greasing']},
        ],
    },
    {
        "section": 'Terrace',
        "equipment": [
            {"sr_no": 31, "equipment": 'Fire Hydrant Booster Pump', "checkpoints": ['Motor', 'Pump']},
            {"sr_no": 32, "equipment": 'Pressure Switch/Guage', "checkpoints": ['Panel Display', 'Auto peration']},
            {"sr_no": 33, "equipment": 'Pan Coater', "checkpoints": ['Bucket integrity', 'Greasing/Oiling', 'Motor']},
            {"sr_no": 34, "equipment": 'Exhaust Fans -1/2/3', "checkpoints": ['Mesh/Filter', 'Motor']},
            {"sr_no": 35, "equipment": 'Hand Pallet Truck', "checkpoints": ['Oil/greasing']},
        ],
    },
    {
        "section": 'External Area',
        "equipment": [
            {"sr_no": 36, "equipment": 'Fire Hydrant Pump Jockey 7.5', "checkpoints": ['Motor', 'Pump', 'Pressure Switch/Guage', 'Panel Display', 'Auto peration']},
            {"sr_no": 37, "equipment": 'Fire Hydrant Main 20 hp', "checkpoints": ['Motor', 'Pump', 'Pressure Switch/Guage', 'Panel Display', 'Auto peration']},
            {"sr_no": 38, "equipment": 'Water Pump', "checkpoints": ['Motor']},
            {"sr_no": 39, "equipment": 'UG TANK 1/2', "checkpoints": ['Motor']},
        ],
    },
    {
        "section": 'Miscallenous',
        "equipment": [
            {"sr_no": 40, "equipment": 'Air Condition', "checkpoints": ['Compress Air', 'Filter']},
        ],
    },
]

CATALOG_A185 = [
    {
        "section": 'Ground floor',
        "equipment": [
            {"sr_no": 1, "equipment": 'Inspection Feeder', "checkpoints": ['tightness of foundation bolts']},
            {"sr_no": 2, "equipment": 'Electric connections', "checkpoints": ['Weighing Belt', 'belt condition', 'tightness of foundation bolts', 'Clean load cells externally', 'Electric connections']},
            {"sr_no": 3, "equipment": 'oiling / greasing', "checkpoints": ['Bucket Elevator', 'belt condition', 'oiling / greasing', 'Check tightness of foundation bolts']},
            {"sr_no": 4, "equipment": 'Auto L-sealer', "checkpoints": ['(shrink wrapper)', 'Lubrication']},
            {"sr_no": 5, "equipment": 'Bi Directional Conveyor A', "checkpoints": ['oiling / greasing', 'Check motor cable connector']},
            {"sr_no": 6, "equipment": 'Bi Directional Conveyor B', "checkpoints": ['Check belt integrity', 'oiling / greasing']},
            {"sr_no": 7, "equipment": 'Check motor cable connector', "checkpoints": ['Dryer Forward Conveyor', 'Check belt integrity', 'oiling / greasing', 'Check motor cable connector']},
            {"sr_no": 8, "equipment": 'Dryer Reverse Conveyor', "checkpoints": ['Check belt integrity', 'oiling / greasing']},
            {"sr_no": 9, "equipment": 'Check motor cable connector', "checkpoints": ['Dryer circ. blower Side A', 'Check foundation bolts for tightness', 'Check for vibration, attend if any', 'Check motor cable connector']},
            {"sr_no": 10, "equipment": 'Dryer circ. blower Side B', "checkpoints": ['Check Cleaning of filter and internal', 'parts', 'Check motor cable connector']},
            {"sr_no": 11, "equipment": 'Dryer Burner 1', "checkpoints": ['Check flame sensing', 'Check holding down bolts', 'Check elect. connections']},
            {"sr_no": 12, "equipment": 'Dryer Burner 2', "checkpoints": ['Check flame sensing', 'Check holding down bolts']},
            {"sr_no": 13, "equipment": 'Check elect. connections', "checkpoints": ['Dryer Belt', 'Check belt integrity', 'oiling / greasing', 'Check belt drive chain lubrication', 'Check motor cable connector']},
            {"sr_no": 14, "equipment": 'Dryer Exhaust Fan A', "checkpoints": ['Check foundation bolts for tightness', 'Check for vibration, attend if any', 'Check motor cable connector']},
            {"sr_no": 15, "equipment": 'Dryer Exhaust Fan B', "checkpoints": ['Check foundation bolts for tightness', 'Check for vibration, attend if any', 'Check motor cable connector']},
            {"sr_no": 16, "equipment": 'Conveyor with Diverter', "checkpoints": ['Motor check']},
            {"sr_no": 17, "equipment": 'Check Lubrication', "checkpoints": ['Diverter Chute B', 'Lubrication']},
            {"sr_no": 18, "equipment": 'Return Line Conveyor', "checkpoints": ['Check conveyor integrity']},
            {"sr_no": 19, "equipment": 'oiling / greasing', "checkpoints": ['Check motor connections', 'Retention Tumbler', 'Check conveyor', 'oiling / greasing', 'Check motor connections']},
            {"sr_no": 20, "equipment": 'Salinity Centrifugal Pump', "checkpoints": ['Check pump and motor', 'oiling / greasing', 'Check foundation bolts', 'Check elect. Connections']},
            {"sr_no": 21, "equipment": 'Slurry Peristaltic Pump', "checkpoints": ['Check pump and motor', 'oiling / greasing', 'Check foundation bolts', 'Check elect. Connections']},
            {"sr_no": 22, "equipment": 'Salinity Centrifugal Pump', "checkpoints": ['Check pump and motor', 'Check lubrication', 'Check foundation bolts', 'Check elect. Connections']},
            {"sr_no": 23, "equipment": 'Slurry Peristaltic Pump', "checkpoints": ['Check pump and motor', 'oiling / greasing']},
            {"sr_no": 24, "equipment": 'Check foundation bolts', "checkpoints": ['Check elect. Connections', 'Salinity Peristaltic Pump', 'Check pump and motor', 'oiling / greasing', 'Check foundation bolts', 'Check elect. Connections']},
            {"sr_no": 25, "equipment": 'Make up Centrifugal Pump', "checkpoints": ['(dispensing', 'Check pump and motor', 'oiling / greasing', 'Check foundation bolts', 'Check elect. Connections']},
            {"sr_no": 26, "equipment": 'Salinity Agitator A', "checkpoints": ['Check agitator fasteners', 'oiling / greasing', 'Check salinity sensor']},
            {"sr_no": 27, "equipment": 'Salinity Agitator B', "checkpoints": ['Check agitator fasteners', 'Check motor lubrication', 'Check salinity sensor']},
            {"sr_no": 28, "equipment": 'Salinity tank A Heater', "checkpoints": ['Element heater check', 'Sealing base check']},
            {"sr_no": 29, "equipment": 'Transformer check', "checkpoints": ['Salinity tank B Heater', 'Element heater check', 'Sealing base check', 'Transformer check']},
            {"sr_no": 30, "equipment": 'Diverter Chute C, Dewatering', "checkpoints": ['Lubrication']},
            {"sr_no": 31, "equipment": 'Transfer Conveyor', "checkpoints": ['Check motor connections', 'oiling / greasing', 'Check conveyor Integrity']},
            {"sr_no": 32, "equipment": 'Diverter Chute D', "checkpoints": ['Lubrication']},
            {"sr_no": 33, "equipment": 'Ribbon Blender', "checkpoints": ['Check motor connections', 'oiling / greasing', 'Check fasteners', 'Check cover Sensor interlock']},
            {"sr_no": 34, "equipment": 'oiling / greasing', "checkpoints": ['Screw Conveyor', 'Check motor connections', 'Check clearance between screw and', 'housing', 'oiling / greasing']},
            {"sr_no": 35, "equipment": 'Check fasteners', "checkpoints": ['Feeding Hopper Vibrator', '(Powder)', 'Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 36, "equipment": 'Feeding Hopper Vibrator A', "checkpoints": ['(Peanut)']},
            {"sr_no": 37, "equipment": 'Check vibrator elect connections', "checkpoints": ['Check fasteners', 'Cable Vey', 'Check drive motor connections', 'Check air pressure', 'Check smooth movements of', 'conveyor discs.', 'Check gates']},
            {"sr_no": 38, "equipment": 'Syrup Peristaltic Pump', "checkpoints": ['Check pump piping for leakage', 'Check motor connections']},
            {"sr_no": 39, "equipment": 'oiling / greasing', "checkpoints": ['Syrup Makeup Centrifugal Pump', 'Check pump piping for leakage', 'Check motor connections', 'oiling / greasing']},
            {"sr_no": 40, "equipment": 'Syrup Tank 1 Agita. Motor', "checkpoints": ['Check motor connections']},
            {"sr_no": 42, "equipment": 'oiling / greasing', "checkpoints": ['Syrup Tank 2 Agita. Motor', 'Check motor connections']},
            {"sr_no": 43, "equipment": 'oiling / greasing', "checkpoints": ['Syrup Tank 1 Heater', 'Cooler check', 'Motor check', 'Temperature meter check']},
            {"sr_no": 44, "equipment": 'Extruder, Main Motor', "checkpoints": ['Check V belts', 'oiling / greasing', 'Check oil sealing', 'Check motor bearing lubrication', 'Check foundation bolts']},
            {"sr_no": 45, "equipment": 'Extruder Cutter', "checkpoints": ['Check motor connection']},
            {"sr_no": 46, "equipment": 'Check fasteners', "checkpoints": ['Extruder Vibrator Feeder', 'Check elect. Connections', 'Check vibration, material flow']},
            {"sr_no": 47, "equipment": 'Extruder Agitator', "checkpoints": ['Check elect connections', 'oiling / greasing', 'Check agitator blades, fasteners']},
            {"sr_no": 48, "equipment": 'Extruder Hopper Screw Feeder', "checkpoints": ['Check elect connections', 'oiling / greasing']},
            {"sr_no": 49, "equipment": 'Check Screw', "checkpoints": ['Extruder Heater', 'Check heater connections', 'Check temperature indication']},
            {"sr_no": 50, "equipment": 'L Conveyor', "checkpoints": ['Check motor connections', 'oiling / greasing', 'Check conveyor']},
            {"sr_no": 51, "equipment": 'LIW Hopper- Vibrator Peanut', "checkpoints": ['Check load cell cleanliness', 'Check elect connections']},
            {"sr_no": 52, "equipment": 'Pan Coater-1 Tumbler', "checkpoints": ['Check motor connection', 'Check drive lubrication']},
            {"sr_no": 53, "equipment": 'Pan Coater-1 Conveyor', "checkpoints": ['Check motor connections', 'oiling / greasing', 'Check conveyor']},
            {"sr_no": 54, "equipment": 'Pan Coater-1 Powder Hopper', "checkpoints": ['Vibratory Feeder ( Cab Levy G1)', 'Check vibrator elect connections']},
            {"sr_no": 55, "equipment": 'Check fasteners', "checkpoints": ['Pan Coater-1 Powder Vibrator', 'Check vibrator elect connections']},
            {"sr_no": 56, "equipment": 'Check fasteners', "checkpoints": ['RO water purifier 2000ltr/hr', 'Tank integrity', 'Filter', 'motor']},
            {"sr_no": 57, "equipment": 'Pan Coater-1 Syrup A', "checkpoints": ['Check elect connections', 'Motor check', 'Sensor check', 'oiling / greasing', 'Conveyor belt check-up and clean']},
            {"sr_no": 58, "equipment": 'Pan Coater-1 Syrup B', "checkpoints": ['Check elect connections', 'Motor check', 'Sensor check']},
            {"sr_no": 59, "equipment": 'oiling / greasing', "checkpoints": ['LIW Hopper- Vibrator Peanut,', 'Pan coater 2', 'Check motor connection']},
            {"sr_no": 60, "equipment": 'Check drive lubrication', "checkpoints": []},
            {"sr_no": 61, "equipment": 'oiling / greasing', "checkpoints": ['Check motor connections', 'Check conveyor', 'Pan Coater-2 Powder Hopper', 'Vibratory Feeder (Cablevey', 'G4)', 'Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 63, "equipment": 'Pan Coater-2 Powder Vibrator', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 64, "equipment": 'Pan Coater-2 Syrup A', "checkpoints": ['Check elect connections', 'Motor check', 'Sensor check', 'oiling / greasing', 'Conveyor belt check-up and clean']},
            {"sr_no": 65, "equipment": 'Pan Coater-2 Syrup B', "checkpoints": ['Check elect connections', 'Motor check', 'Sensor check', 'oiling / greasing', 'Conveyor belt check-up and clean']},
            {"sr_no": 66, "equipment": 'Check load cell cleanliness', "checkpoints": ['Check elect connections']},
            {"sr_no": 67, "equipment": 'HMC', "checkpoints": ['Check motor connection', 'oiling / greasing']},
            {"sr_no": 68, "equipment": 'Pan coater -3 Conveyor', "checkpoints": ['oiling / greasing', 'Check motor connections', 'Check conveyor', 'Pan coater -3 Powder Vibrator']},
            {"sr_no": 69, "equipment": 'Check vibrator elect connections', "checkpoints": ['Check fasteners', 'Pan coater -3 Syrup A']},
            {"sr_no": 70, "equipment": 'Check elect connections', "checkpoints": ['Motor check', 'Sensor check', 'oiling / greasing', 'Conveyor belt check-up and clean']},
            {"sr_no": 71, "equipment": 'Conveyor belt check-up and clean', "checkpoints": []},
            {"sr_no": 72, "equipment": 'Main Transfer Conveyor', "checkpoints": ['oiling / greasing', 'Check motor connections', 'Check conveyor']},
            {"sr_no": 73, "equipment": 'Buffer Shifter', "checkpoints": ['Heater check', 'Motor check', 'Temperature meter check', 'Temperature meter check', 'Inclined Conveyor A']},
            {"sr_no": 74, "equipment": 'oiling / greasing', "checkpoints": ['Check motor connections', 'Check conveyor']},
            {"sr_no": 75, "equipment": 'Puffer Drum', "checkpoints": ['Check drum drive motor foundation', 'bolts', 'Check motor electrical connections', 'Check sprocket and chain', 'lubrication', 'Puffer Blower']},
            {"sr_no": 76, "equipment": 'Check motor foundation bolts', "checkpoints": ['Check blower impeller', 'Puffer Vibratory Feeder']},
            {"sr_no": 77, "equipment": 'Check vibrator elect connections', "checkpoints": ['Check fasteners']},
            {"sr_no": 78, "equipment": 'Puffer Burner', "checkpoints": ['Check gas piping for leaks', 'Check flame sensor function']},
            {"sr_no": 79, "equipment": 'Cooling Tumbler', "checkpoints": ['Check motor connection', 'Check motor lubrication', 'Check motor foundation bolts', 'Cooling Tumbler Blower 1']},
            {"sr_no": 80, "equipment": 'Check motor foundation bolts', "checkpoints": ['Check belt tension', 'Check blower impeller', 'Check impeller locking, key', 'Check motor connections']},
            {"sr_no": 81, "equipment": 'Cooling Tumbler Blower 2', "checkpoints": ['Check motor foundation bolts', 'Check belt tension', 'Check blower impeller', 'Check impeller locking, key', 'Check motor connections']},
            {"sr_no": 82, "equipment": 'Check motor connections', "checkpoints": ['Check conveyor']},
            {"sr_no": 83, "equipment": 'Feeding Hopper Vibrator, A', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 84, "equipment": 'Feeding Hopper Vibrator B', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 85, "equipment": 'Nested Feeder 1', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 86, "equipment": 'Nested Feeder 2', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 87, "equipment": 'Nested Feeder 3', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 89, "equipment": 'Kettle 1- Centrifugal Pump', "checkpoints": ['Check motor connections', 'Motor check', 'Check pump']},
            {"sr_no": 90, "equipment": 'Motor check', "checkpoints": ['Check pump']},
            {"sr_no": 91, "equipment": 'Kettle -1 agitator', "checkpoints": ['Check motor connections', 'Motor check', 'Check agitator blades', 'Kettle- 2 Agitator']},
            {"sr_no": 92, "equipment": 'Check motor connections', "checkpoints": ['Motor check', 'Check agitator blades', 'Kettler-1 Heater']},
            {"sr_no": 93, "equipment": 'Check connections', "checkpoints": ['Check working', 'Check sensor']},
            {"sr_no": 94, "equipment": 'Kettler-2 Heater', "checkpoints": ['Check connections', 'Check working', 'Check sensor']},
            {"sr_no": 95, "equipment": 'Peristaltic Pump', "checkpoints": ['Check motor connections', 'Motor check', 'Check pump condition', 'DFH Screw']},
            {"sr_no": 96, "equipment": 'Check motor connections', "checkpoints": ['Motor check', 'Check screw condition', 'DFH Agitator']},
            {"sr_no": 97, "equipment": 'Check motor connections', "checkpoints": ['Motor check', 'Check agitator blades', 'DFH Scarf Feeder']},
            {"sr_no": 98, "equipment": 'Check Cleaning', "checkpoints": ['Check vibrator elect connections', 'Check fasteners']},
            {"sr_no": 99, "equipment": 'Seasoning Drum', "checkpoints": ['Check motor foundation bolts', 'oiling / greasing', 'Check motor connections', 'Check cleaning', 'Retention Conveyor']},
            {"sr_no": 100, "equipment": 'Check motor connections', "checkpoints": ['Check motor lubrication', 'Check conveyor', 'Dryer Spreader Belt']},
            {"sr_no": 101, "equipment": 'Check spreader fasteners', "checkpoints": ['oiling / greasing']},
            {"sr_no": 102, "equipment": 'New Vibrator', "checkpoints": ['Check elect connections', 'Check vibrations']},
            {"sr_no": 103, "equipment": 'Destoner with Blower', "checkpoints": ['Check motor', 'oiling / greasing', 'Check elect connections', 'Check foundation bolts', 'Z Conveyor for Destoner']},
            {"sr_no": 104, "equipment": 'Tank check', "checkpoints": ['Filter check', 'Motor check']},
            {"sr_no": 105, "equipment": 'FFS Machine', "checkpoints": ['Check sensor', 'Motor check', 'Check heaters', 'Check belts', 'oiling / greasing']},
            {"sr_no": 106, "equipment": 'Motor check', "checkpoints": ['Check heaters', 'Check belts', 'oiling / greasing']},
            {"sr_no": 107, "equipment": 'Roll Rewinding Machine', "checkpoints": ['Check sensor', 'Motor check', 'oiling / greasing']},
            {"sr_no": 108, "equipment": 'Conveyorized Metal Detector', "checkpoints": ['Motor check', 'Check elect connections', 'Check conveyor Belt', 'Check metal detection', 'oiling / greasing']},
            {"sr_no": 109, "equipment": 'Pet Sealing Machine', "checkpoints": ['Motor check', 'Check elect connections', 'Check sealing heaters', 'Check heater condition', 'Check conveyor Belt', 'oiling / greasing', 'Continuous Band Sealer Machine']},
            {"sr_no": 110, "equipment": 'Motor check', "checkpoints": ['Check elect connections', 'Check sealing heaters', 'Check heater condition', 'conveyor belt integrity', 'oiling / greasing', 'Flow Wrap Machine, Tunnel']},
            {"sr_no": 111, "equipment": 'Motor check', "checkpoints": ['Check elect connections', 'Check sealing heaters', 'Check heater condition', 'Check Fan', 'conveyor Belt integrity', 'oiling / greasing']},
            {"sr_no": 112, "equipment": 'Pakona PFS', "checkpoints": ['Motor check', 'Check elect connections', 'conveyor belt integrity', 'oiling / greasing', 'Check vacuum', 'UPS 300 KVS']},
            {"sr_no": 113, "equipment": 'OEM service checks', "checkpoints": ['Underground Tank Water 15000']},
            {"sr_no": 114, "equipment": 'Ltrs', "checkpoints": ['Check filling pipe line condition', 'Check level switch', 'Underground Water Tank Pump']},
            {"sr_no": 115, "equipment": 'Pump, Motor check', "checkpoints": ['Check connections', 'Check level sw operation', 'Check level sw operation', 'MIDC Water Overhead Tank']},
            {"sr_no": 116, "equipment": '6000 Ltrs', "checkpoints": ['Piping check', 'MIDC Water Overhead Tank', '6000 Ltrs']},
            {"sr_no": 117, "equipment": 'Piping check', "checkpoints": []},
            {"sr_no": 118, "equipment": 'water Filtration Plant', "checkpoints": ['Check piping and vessels for leak', 'oiling / greasing', 'Check elect. connection', 'Filtered Water Tank 10000 Ltrs']},
            {"sr_no": 119, "equipment": 'Piping check', "checkpoints": []},
            {"sr_no": 120, "equipment": 'Pump, Motor lubrication check', "checkpoints": []},
            {"sr_no": 121, "equipment": 'Reach Truck', "checkpoints": ['OEM service checks', 'Battery, check']},
            {"sr_no": 122, "equipment": 'CCP Blender 1', "checkpoints": ['Check fasteners', 'Check chain, bearing lubrication', 'Motor check', 'Check elect. Connections', 'CCP']},
            {"sr_no": 123, "equipment": 'continuous band sealer', "checkpoints": ['Motor check', 'Check elect connections', 'Check sealing heaters', 'Check heater condition', 'Check conveyor belt', 'oiling / greasing']},
            {"sr_no": 124, "equipment": 'Blender 2', "checkpoints": ['Check fasteners', 'Check chain, bearing lubrication', 'Motor check', 'Check elect. Connections', 'CCP', 'continuous band sealer']},
            {"sr_no": 125, "equipment": 'Motor check', "checkpoints": ['Check elect connections', 'Check sealing heaters', 'Check heater condition', 'conveyor belt integrity', 'oiling / greasing', 'Vibrative', 'Check fasteners', 'Check spring condition', 'Check motor connections', 'oiling / greasing', 'Check sieving screens']},
            {"sr_no": 126, "equipment": 'Continuous Band Sealer', "checkpoints": ['Motor check', 'Line check', 'Valve check', 'Compressor check']},
            {"sr_no": 127, "equipment": 'Foot Sealer', "checkpoints": ['Check elect connections', 'Check heater']},
            {"sr_no": 128, "equipment": 'UPS Room AC 1, 2', "checkpoints": ['Clean condenser', 'Check elect connections']},
            {"sr_no": 130, "equipment": 'Clean air filter', "checkpoints": ['Check drain line', 'Lab AC', 'Clean condenser', 'Check elect connections', 'Clean air filter', 'Check drain line', 'CCP Blender1 Room AC1, AC2', 'Clean condenser', 'Check elect connections', 'Clean air filter']},
            {"sr_no": 131, "equipment": 'Check drain line', "checkpoints": ['Blender 2 Room AC1, AC2', 'Clean condenser', 'Check elect connections', 'Clean air filter', 'Check drain line']},
            {"sr_no": 132, "equipment": 'Server Room AC', "checkpoints": ['Clean condenser', 'Check elect connections', 'Clean air filter']},
            {"sr_no": 133, "equipment": 'Check drain line', "checkpoints": ['Cold Room AC1, AC2, AC3, AC$', 'Clean condenser']},
            {"sr_no": 134, "equipment": 'Check elect connections', "checkpoints": ['Clean air filter', 'Check drain line', 'CEO Office AC', 'Clean condenser', 'Check elect connections', 'Clean air filter']},
            {"sr_no": 135, "equipment": 'Check drain line', "checkpoints": ['Conference Room AC', 'Clean condenser', 'Check elect connections', 'Clean air filter']},
            {"sr_no": 136, "equipment": 'Check drain line', "checkpoints": ['Creshe AC', 'Clean condenser', 'Check elect connections', 'Clean air filter']},
            {"sr_no": 137, "equipment": 'Check drain line', "checkpoints": ['Water Cooler', 'Motor check', 'Line check']},
            {"sr_no": 138, "equipment": 'Valve check', "checkpoints": ['Air Compressor', 'Tank check']},
            {"sr_no": 139, "equipment": 'Check filter', "checkpoints": ['oiling / greasing', 'Check elect connections', 'Motor check', 'Air Dryer', 'Tank check', 'Check filter', 'oiling / greasing', 'Check elect connections', 'Check drain trap', 'Check dew point']},
            {"sr_no": 140, "equipment": 'Air Compressor', "checkpoints": ['oiling / greasing', 'Check filter']},
            {"sr_no": 141, "equipment": 'Motor check', "checkpoints": ['Air Dryer', 'oiling / greasing', 'Check elect connections', 'Check drain trap']},
            {"sr_no": 142, "equipment": 'Nitrogen Plant', "checkpoints": ['Motor check']},
            {"sr_no": 143, "equipment": 'Line check', "checkpoints": ['Dock', 'Motor connections check']},
            {"sr_no": 144, "equipment": 'oiling / greasing', "checkpoints": ['Fire Water Pump 1', 'Motor check', 'Line check', 'Valve check', 'Check foundation bolts']},
            {"sr_no": 145, "equipment": 'Check coupling', "checkpoints": ['Fire Water Pump 2', 'Motor check', 'Line check', 'Valve check', 'Check foundation bolts']},
            {"sr_no": 146, "equipment": 'Check coupling', "checkpoints": ['Fire Alarm Panel', 'Check alarm']},
            {"sr_no": 147, "equipment": 'Check elect. Connections', "checkpoints": ['Videojet printer', 'Check conveyor', 'Check printer']},
            {"sr_no": 148, "equipment": 'Reach Truck', "checkpoints": ['Carry preventive checks by OEM']},
            {"sr_no": 149, "equipment": 'Check battery charger', "checkpoints": ['Battery', 'operated Pellet TrucK']},
            {"sr_no": 150, "equipment": 'Check battery charge', "checkpoints": ['Check Lifting Mechanism', 'Control Panel 1 (A)', 'Clean AC filter', 'Check UPS connections']},
            {"sr_no": 151, "equipment": 'Check Earthing', "checkpoints": ['Control Panel 2 (B)', 'Clean AC filter', 'Check UPS connections', 'Check Earthing']},
            {"sr_no": 152, "equipment": 'Fire extinguishers ABC, CO2', "checkpoints": ['Check Gas pressure']},
            {"sr_no": 153, "equipment": 'Check validity', "checkpoints": ['Fire Water Pump Panel', 'Check alarm is working']},
            {"sr_no": 154, "equipment": 'Check connections', "checkpoints": ['Air Receiver (2 M3)', 'Check foundation bolts tightness', 'Check for safety valve leakage']},
            {"sr_no": 155, "equipment": 'Nitrogen Receiver ( 2 M3)', "checkpoints": ['Check foundation bolts tightness']},
            {"sr_no": 156, "equipment": 'Check for safety valve leakage', "checkpoints": ['HT', 'Transformer ( 630 KVA)']},
            {"sr_no": 157, "equipment": 'Check Earthings', "checkpoints": ['Clean externally', 'Check oil level', 'Metering Kiosk', 'Check Earthing']},
            {"sr_no": 158, "equipment": 'Clean externally', "checkpoints": ['RMU, HT Breaker', 'Check Earthing', 'Clean Externally']},
            {"sr_no": 159, "equipment": 'LT Panel', "checkpoints": []},
            {"sr_no": 160, "equipment": 'Check Earthing', "checkpoints": ['Check tightness of internal', 'connections']},
            {"sr_no": 161, "equipment": 'Utility Panel', "checkpoints": ['Check Earthing', 'Check tightness of internal', 'connections']},
            {"sr_no": 162, "equipment": 'Emergency Panel', "checkpoints": ['Check Earthing', 'Check tightness of internal', 'connections', 'Emergency Panel']},
            {"sr_no": 163, "equipment": 'Check tightness of internal', "checkpoints": ['connections', 'Hydraulic press machine']},
            {"sr_no": 164, "equipment": 'Air curtain', "checkpoints": []},
            {"sr_no": 165, "equipment": 'Check Door position', "checkpoints": ['check elect connection', 'Check limit switch and on-off', 'operation.', 'Windows and mesh']},
            {"sr_no": 166, "equipment": 'Doors and gaps', "checkpoints": []},
            {"sr_no": 168, "equipment": 'Pestoflash Machines', "checkpoints": []},
            {"sr_no": 169, "equipment": 'Drainage and mesh coverings', "checkpoints": []},
            {"sr_no": 170, "equipment": 'gaskets (for all machines )', "checkpoints": ['Lids of all equipments (acrylic or']},
            {"sr_no": 172, "equipment": 'Purifier Water Cooler', "checkpoints": []},
        ],
    },
]

CATALOG = {"MONTHLY": CATALOG_50A, "QUARTERLY": CATALOG_50B, "A185": CATALOG_A185}


def is_after_maintenance(checkpoint: str) -> bool:
    return checkpoint in AFTER_MAINTENANCE


def full_form_items(form_type: str) -> list[dict]:
    """All rows of a form as UNSET checklist items. Real machines (those with checkpoints)
    get their maintenance checkpoints PLUS the 4 After-Maintenance checks appended."""
    items = []
    for sec in CATALOG.get(form_type, []):
        for eq in sec["equipment"]:
            if eq["checkpoints"]:
                cps = eq["checkpoints"] + AFTER_MAINTENANCE   # maintenance + after-maintenance
            else:
                cps = [eq["equipment"]]                        # checkpoint-less misc row = self
            for cp in cps:
                items.append({
                    "section": sec["section"], "equipment": eq["equipment"],
                    "sr_no": eq["sr_no"], "equipment_date": "",
                    "checkpoint": cp, "status": "UNSET", "remarks": "",
                })
    return items
