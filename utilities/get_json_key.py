import sys
import ijson
import json

filename = sys.argv[1]
wanted_key = sys.argv[2]

with open(filename, "rb") as f:
    for key, value in ijson.kvitems(f, ""):
        if key == wanted_key:
            print(json.dumps(value, ensure_ascii=False))
            break
