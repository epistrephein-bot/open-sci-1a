import json
import random
import ijson

input_file = "../data/iris_openaire_organizations/omid_organizations.json"
output_file = "../sample/iris_openaire_organizations/omid_organizations.sample.json"
sample_size = 5000

sample = []
count = 0

with open(input_file, "rb") as f:
    for key, value in ijson.kvitems(f, ""):
        count += 1

        item = (key, value)

        if len(sample) < sample_size:
            sample.append(item)
        else:
            j = random.randrange(count)
            if j < sample_size:
                sample[j] = item

result = dict(sample)

with open(output_file, "w", encoding="utf-8") as out:
    json.dump(result, out, ensure_ascii=False, indent=2)

print(f"Sampled {len(result)} items from {count} total items")
