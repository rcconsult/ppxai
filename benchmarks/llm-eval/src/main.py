import os
import json

def main():
    with open('config.json') as f:
        config = json.load(f)
    print("Done")

if __name__ == "__main__":
    main()
