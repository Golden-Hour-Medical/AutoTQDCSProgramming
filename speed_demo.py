#!/usr/bin/env python3
"""
Audio Downloader Speed Demo
Shows the theoretical speed improvements from optimization.
"""

import time

def calculate_transfer_time(file_size, chunk_size, piece_size, piece_delay):
    """Calculate theoretical transfer time including flash write delays."""
    pieces_per_chunk = chunk_size // piece_size
    total_chunks = (file_size + chunk_size - 1) // chunk_size  # Ceiling division
    total_pieces = total_chunks * pieces_per_chunk
    
    # Time from delays alone
    delay_time = total_pieces * piece_delay
    
    # Approximate transmission time at 115200 baud (roughly 11.5KB/s effective)
    transmission_time = file_size / 11520  # bytes per second
    
    # FLASH WRITE TIME - This is the critical bottleneck!
    # Flash storage typically writes at 10-50KB/s depending on chip and wear
    # We'll assume conservative 15KB/s write speed for flash
    flash_write_time = file_size / (15 * 1024)  # 15KB/s flash write speed
    
    # Add chunk acknowledgment delays (assuming 50ms per chunk for flash processing)
    chunk_ack_time = total_chunks * 0.05  # 50ms per chunk
    
    # Total time is the sum of all bottlenecks
    total_time = delay_time + transmission_time + flash_write_time + chunk_ack_time
    return total_time, delay_time, transmission_time, flash_write_time, chunk_ack_time

def main():
    print("🎵 Audio Downloader Speed Analysis")
    print("=" * 50)
    
    # Test with your file size (103,438 bytes from the output)
    file_size = 103438
    
    print(f"File size: {file_size:,} bytes ({file_size/1024:.1f} KB)")
    print()
    
    # Original settings
    print("📊 ORIGINAL SETTINGS:")
    orig_time, orig_delay, orig_trans, orig_flash, orig_ack = calculate_transfer_time(
        file_size, 1024, 64, 0.002
    )
    print(f"  Chunk: 1024B, Piece: 64B, Delay: 2.0ms")
    print(f"  Total time: {orig_time:.1f}s")
    print(f"  Delay time: {orig_delay:.1f}s ({orig_delay/orig_time*100:.1f}%)")
    print(f"  Transmission: {orig_trans:.1f}s ({orig_trans/orig_time*100:.1f}%)")
    print(f"  Flash write: {orig_flash:.1f}s ({orig_flash/orig_time*100:.1f}%)")
    print(f"  Chunk ack: {orig_ack:.1f}s ({orig_ack/orig_time*100:.1f}%)")
    print(f"  Speed: {file_size/1024/orig_time:.1f} KB/s")
    print()
    
    # Optimized standard settings
    print("🚀 OPTIMIZED STANDARD:")
    std_time, std_delay, std_trans, std_flash, std_ack = calculate_transfer_time(
        file_size, 1024, 128, 0.005
    )
    print(f"  Chunk: 1024B, Piece: 128B, Delay: 5.0ms")
    print(f"  Total time: {std_time:.1f}s")
    print(f"  Delay time: {std_delay:.1f}s ({std_delay/std_time*100:.1f}%)")
    print(f"  Transmission: {std_trans:.1f}s ({std_trans/std_time*100:.1f}%)")
    print(f"  Flash write: {std_flash:.1f}s ({std_flash/std_time*100:.1f}%)")
    print(f"  Chunk ack: {std_ack:.1f}s ({std_ack/std_time*100:.1f}%)")
    print(f"  Speed: {file_size/1024/std_time:.1f} KB/s")
    print(f"  📈 Improvement: {orig_time/std_time:.1f}x faster!")
    print()
    
    # Fast mode settings
    print("⚡ FAST MODE:")
    fast_time, fast_delay, fast_trans, fast_flash, fast_ack = calculate_transfer_time(
        file_size, 2048, 128, 0.002
    )
    print(f"  Chunk: 2048B, Piece: 128B, Delay: 2.0ms")
    print(f"  Total time: {fast_time:.1f}s")
    print(f"  Delay time: {fast_delay:.1f}s ({fast_delay/fast_time*100:.1f}%)")
    print(f"  Transmission: {fast_trans:.1f}s ({fast_trans/fast_time*100:.1f}%)")
    print(f"  Flash write: {fast_flash:.1f}s ({fast_flash/fast_time*100:.1f}%)")
    print(f"  Chunk ack: {fast_ack:.1f}s ({fast_ack/fast_time*100:.1f}%)")
    print(f"  Speed: {file_size/1024/fast_time:.1f} KB/s")
    print(f"  📈 Improvement: {orig_time/fast_time:.1f}x faster!")
    print()
    
    print("💡 SUMMARY:")
    print(f"  Original: {orig_time:.1f}s → Standard: {std_time:.1f}s → Fast: {fast_time:.1f}s")
    print(f"  Speed improvements: {orig_time/std_time:.1f}x → {orig_time/fast_time:.1f}x")
    print()
    print("⚠️  NOTE: Fast mode requires:")
    print("   - Stable serial connection")
    print("   - Device with adequate buffer handling")
    print("   - Good USB cable and port")

if __name__ == "__main__":
    main() 