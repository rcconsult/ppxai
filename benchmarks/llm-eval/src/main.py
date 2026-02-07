import os
import json
import json

def main():
    with open('config.json') as f:
        config = json.load(f)
    with open('config.json', 'r') as f:
        config = json.load(f)
    print("Done")

if __name__ == "__main__":
    main()
