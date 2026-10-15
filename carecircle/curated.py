"""Small curated supplement: common drugs reported in FDA labels as substrates of an enzyme. NOT verified against labels here:
shown in the product as 'curated (unverified)' and must be checked against the label/FDA source before any real use."""
CURATED_SUBSTRATES = [
    ("simvastatin", "CYP3A", "x"), ("atorvastatin", "CYP3A", "x"), ("amlodipine", "CYP3A", "x"),
    ("warfarin", "CYP2C9", "x"), ("omeprazole", "CYP2C19", "x"), ("clopidogrel", "CYP2C19", "x"),
    ("metoprolol", "CYP2D6", "x"), ("codeine", "CYP2D6", "x"), ("tramadol", "CYP2D6", "x"),
]
