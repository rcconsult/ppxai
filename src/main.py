import os
import json
import json


def main():
    print("Starting...")
    with open("config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    print("Done")


if __name__ == "__main__":
    main()

