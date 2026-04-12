"""
Key Generator Script - Creates unique activation keys for Pinaki
Run this script to generate new activation keys for distribution to users
"""

import secrets
import string
from datetime import datetime, timedelta
from pathlib import Path
import json


def generate_activation_key() -> str:
    """
    Generate a unique activation key in format: PINAKI-XXXX-XXXX-XXXX-XXXX
    Using Base32 characters for readability (avoiding confusing chars like 0/O, 1/I/L)
    """
    # Use Base32 alphabet (A-Z, 2-7) - more readable than full Base64
    alphabet = string.ascii_uppercase + "234567"
    
    # Generate 16 random characters
    random_chars = ''.join(secrets.choice(alphabet) for _ in range(16))
    
    # Format as PINAKI-XXXX-XXXX-XXXX-XXXX
    key = f"PINAKI-{random_chars[0:4]}-{random_chars[4:8]}-{random_chars[8:12]}-{random_chars[12:16]}"
    return key


def generate_batch_keys(count: int = 10, output_file: str = "activation_keys.json") -> list:
    """
    Generate a batch of activation keys for distribution
    
    Args:
        count: Number of keys to generate
        output_file: Path to save the generated keys as JSON
        
    Returns:
        List of generated keys
    """
    keys = {
        "generated_date": datetime.now().isoformat(),
        "count": count,
        "keys": [generate_activation_key() for _ in range(count)]
    }
    
    # Save to file
    output_path = Path(output_file)
    with open(output_path, 'w') as f:
        json.dump(keys, f, indent=2)
    
    print(f"✓ Generated {count} activation keys")
    print(f"✓ Saved to: {output_path.absolute()}")
    print(f"\nSample keys:")
    for i, key in enumerate(keys["keys"][:3], 1):
        print(f"  {key}")
    if count > 3:
        print(f"  ... and {count - 3} more keys")
    
    return keys["keys"]


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate Pinaki activation keys")
    parser.add_argument(
        "-c", "--count",
        type=int,
        default=10,
        help="Number of keys to generate (default: 10)"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default="activation_keys.json",
        help="Output file for generated keys (default: activation_keys.json)"
    )
    
    args = parser.parse_args()
    generate_batch_keys(args.count, args.output)
