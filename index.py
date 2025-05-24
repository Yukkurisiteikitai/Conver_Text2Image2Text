def decode_huffman_stream_item(bit_stream, current_pos, reverse_huffman_table, item_name="item"):
    """
    ビットストリームの現在位置から1つのアイテムをハフマンデコードする。
    reverse_huffman_table: {"ビット列": 値}
    戻り値: (デコードされた値, 新しいcurrent_pos) またはエラー
    """
    prefix = ""
    # トライ木を使うとより効率的だが、ここではシンプルな前方一致探索
    for i in range(current_pos, len(bit_stream)):
        prefix += bit_stream[i]
        if prefix in reverse_huffman_table:
            return reverse_huffman_table[prefix], i + 1
            
    # エラー発生時のコンテキスト情報
    context_start = max(0, current_pos - 20)
    context_end = min(len(bit_stream), current_pos + 40) # 少し長めに表示
    error_context = f"...{bit_stream[context_start:current_pos]}[HERE]{bit_stream[current_pos:context_end]}..."
    raise ValueError(
        f"Huffman decode error for {item_name}: No matching code found at position {current_pos}. "
        f"Tried prefix up to '{prefix}'. Stream context: {error_context}"
    )

def decode_image_data(
    encoded_string,
    char_to_bits_map, 
    rep_color_huffman_rev_table, 
    diff_value_huffman_rev_table, 
    count_huffman_rev_table,      
    representative_palette_indices, 
    palette_size,
    image_width,
    image_height
):
    """
    提案された「代表色と差分」方式で圧縮された画像データをデコードする。
    """

    # ステップ1: 文字列表現からビット列へデコード
    bit_stream_list = []
    for char_idx, char_val in enumerate(encoded_string):
        if char_val not in char_to_bits_map:
            raise ValueError(f"Invalid character '{char_val}' at index {char_idx} in encoded string.")
        bit_stream_list.append(char_to_bits_map[char_val])
    bit_stream = "".join(bit_stream_list)

    # ステップ2: ビット列からRLEエンコードされたデータのリストへハフマンデコード
    # 期待する形式: [((代表色ID1, 差分値1), 回数1), ...]
    rle_encoded_data = []
    current_pos = 0
    total_pixels_in_rle_data = 0
    expected_total_pixels = image_width * image_height

    while total_pixels_in_rle_data < expected_total_pixels:
        if current_pos >= len(bit_stream): # ビットストリームが予想より早く尽きた
            if total_pixels_in_rle_data < expected_total_pixels:
                raise ValueError(
                    f"Bit stream ended prematurely. Expected to decode data for {expected_total_pixels} pixels, "
                    f"but RLE data only accounts for {total_pixels_in_rle_data} pixels. "
                    f"Processed {current_pos} of {len(bit_stream)} bits."
                )
            else: # ピクセル数は満たしたが、ストリームの末尾だった場合
                break 
        
        # 1. 代表色IDをデコード
        rep_color_id, current_pos = decode_huffman_stream_item(
            bit_stream, current_pos, rep_color_huffman_rev_table, "representative color ID"
        )
        
        # 2. 差分値をデコード
        diff_value, current_pos = decode_huffman_stream_item(
            bit_stream, current_pos, diff_value_huffman_rev_table, "difference value"
        )
        
        # 3. 連続回数をデコード
        count, current_pos = decode_huffman_stream_item(
            bit_stream, current_pos, count_huffman_rev_table, "RLE count"
        )
        if not isinstance(count, int) or count <= 0:
            raise ValueError(f"Invalid RLE count decoded: {count}. Must be a positive integer.")

        rle_encoded_data.append( ( (rep_color_id, diff_value), count ) )
        total_pixels_in_rle_data += count
    
    if total_pixels_in_rle_data > expected_total_pixels:
        raise ValueError(
            f"RLE data decodes to too many pixels. Expected {expected_total_pixels}, got {total_pixels_in_rle_data}."
        )
    elif total_pixels_in_rle_data < expected_total_pixels and current_pos == len(bit_stream):
        # このケースは上のループ内のチェックで捕捉されるはず
         raise ValueError(
            f"Bit stream fully consumed, but RLE data only accounts for {total_pixels_in_rle_data} pixels. "
            f"Expected {expected_total_pixels} pixels."
        )


    if current_pos < len(bit_stream):
        remaining_bits = bit_stream[current_pos:]
        # 通常、ハフマン符号化されたデータはピッタリ終わるか、明確なパディング規則がある。
        # ここでは残りのビットが全て0であるなどの単純なパディングを仮定することもできるが、
        # 今回は警告を出すに留める。
        print(f"Warning: Bit stream not fully consumed after decoding expected pixel data. "
              f"{len(remaining_bits)} remaining bits: '{remaining_bits[:30]}...'")


    # ステップ3: RLEデコード
    # (代表色ID, 差分値) のペアのシーケンスを復元
    decoded_value_pairs = [] # (rep_color_id, diff_value) のリスト
    for (value_pair, count_val) in rle_encoded_data:
        decoded_value_pairs.extend([value_pair] * count_val)
    
    # RLEデコード後のピクセル数チェック (念のため)
    if len(decoded_value_pairs) != expected_total_pixels:
        raise ValueError(
            f"Internal error: RLE decoded pixel count ({len(decoded_value_pairs)}) "
            f"does not match expected ({expected_total_pixels}) after initial RLE sum matched."
        )

    # ステップ4: ピクセルのパレットインデックスを計算
    final_pixel_palette_indices = []
    for rep_color_id, diff_value in decoded_value_pairs:
        if not (0 <= rep_color_id < len(representative_palette_indices)):
            raise ValueError(
                f"Invalid representative color ID: {rep_color_id}. "
                f"Valid range is 0 to {len(representative_palette_indices) - 1} for list of size {len(representative_palette_indices)}."
            )
        
        actual_representative_palette_index = representative_palette_indices[rep_color_id]
        
        pixel_index_raw = actual_representative_palette_index + diff_value
        
        # パレットインデックスを 0 から palette_size - 1 の範囲に調整 (巡回)
        pixel_index_final = pixel_index_raw % palette_size
        
        final_pixel_palette_indices.append(pixel_index_final)
        
    return final_pixel_palette_indices

# --- 以下はテスト用のコード ---
if __name__ == '__main__':
    # テスト用データ
    char_to_bits_map_example = { # 3-bit encoding example
        'A': "000", 'B': "001", 'C': "010", 'D': "011",
        'E': "100", 'F': "101", 'G': "110", 'H': "111"
    }

    # ハフマン逆引きテーブル (ビット列 -> 値)
    # 代表色ID (0 or 1)
    rep_color_huffman_rev_table_example = {"0": 0, "1": 1}
    # 差分値 (-1, 0, or 1)
    diff_value_huffman_rev_table_example = {"00": 0, "01": 1, "10": -1}
    # 連続回数 (1 or 2)
    count_huffman_rev_table_example = {"0": 1, "1": 2}

    representative_palette_indices_example = [10, 100] # 代表色パレットインデックス
    palette_size_example = 256 # パレットの総色数
    image_width_example = 2
    image_height_example = 2 # 合計4ピクセル

    # エンコードされたデータの例 (手動で作成)
    # 目標ピクセルデータ:
    # 1. (rep_id=0, diff=1), count=1  -> パレットインデックス (10+1)%256 = 11
    # 2. (rep_id=0, diff=0), count=2  -> パレットインデックス (10+0)%256 = 10 (2回)
    # 3. (rep_id=1, diff=-1), count=1 -> パレットインデックス (100-1)%256 = 99
    # 期待される最終パレットインデックスリスト: [11, 10, 10, 99]

    # ハフマン符号化:
    # ((0, 1), 1): rep(0)="0", diff(1)="01", count(1)="0"   => "0010"
    # ((0, 0), 2): rep(0)="0", diff(0)="00", count(2)="1"   => "0001"
    # ((1,-1), 1): rep(1)="1", diff(-1)="10", count(1)="0"  => "1100"
    # 連結ビットストリーム: "001000011100" (12 bits)

    # 文字列表現 (3bit/char):
    # "001" -> 'B'
    # "000" -> 'A'
    # "011" -> 'D'
    # "100" -> 'E'
    encoded_string_example = "BADE"

    print("--- Test Case 1: Basic Valid Data ---")
    try:
        pixel_indices = decode_image_data(
            encoded_string_example,
            char_to_bits_map_example,
            rep_color_huffman_rev_table_example,
            diff_value_huffman_rev_table_example,
            count_huffman_rev_table_example,
            representative_palette_indices_example,
            palette_size_example,
            image_width_example,
            image_height_example
        )
        print(f"Decoded pixel palette indices: {pixel_indices}")
        assert pixel_indices == [11, 10, 10, 99]
        print("Test Case 1 PASSED!")
    except ValueError as e:
        print(f"Test Case 1 FAILED: {e}")

    print("\n--- Test Case 2: Bit stream ends prematurely ---")
    # "00100001110" (最後の '0' が欠落) -> "BAD" と "110" (G) -> "BADG"
    # "0010000111" -> 11 bits, not divisible by 3 for char_to_bits_map_example
    # RLEデータが3ピクセル分しかないケース (4ピクセル期待)
    # ((0, 1), 1) -> "0010"
    # ((0, 0), 1) -> "0000" (diff=0, count=1)
    # ((1,-1), 1) -> "1100"
    # Bitstream: "001000001100" => Encoded: "BACA"
    encoded_string_short = "BACA" # Decodes to 3 pixels
    try:
        pixel_indices = decode_image_data(
            encoded_string_short,
            char_to_bits_map_example,
            rep_color_huffman_rev_table_example,
            diff_value_huffman_rev_table_example,
            count_huffman_rev_table_example, # count table needs "0":1
            representative_palette_indices_example,
            palette_size_example,
            image_width_example, 
            image_height_example # 4 pixels expected
        )
        print(f"Decoded pixel palette indices (should fail): {pixel_indices}")
        print("Test Case 2 FAILED (error was expected but not raised).")
    except ValueError as e:
        print(f"Test Case 2 PASSED (expected error): {e}")

    print("\n--- Test Case 3: Extra bits at the end (Warning expected) ---")
    # "BADEA" -> "001000011100" + "000" (extra "A")
    encoded_string_extra_bits = "BADEA"
    try:
        pixel_indices = decode_image_data(
            encoded_string_extra_bits,
            char_to_bits_map_example,
            rep_color_huffman_rev_table_example,
            diff_value_huffman_rev_table_example,
            count_huffman_rev_table_example,
            representative_palette_indices_example,
            palette_size_example,
            image_width_example,
            image_height_example
        )
        print(f"Decoded pixel palette indices: {pixel_indices}")
        assert pixel_indices == [11, 10, 10, 99] # The core data should still be correct
        print("Test Case 3 PASSED (Warning for extra bits should have been printed).")
    except ValueError as e:
        print(f"Test Case 3 FAILED: {e}")

    print("\n--- Test Case 4: Invalid character in encoded string ---")
    encoded_string_invalid_char = "BADX" # 'X' is not in char_to_bits_map
    try:
        pixel_indices = decode_image_data(
            encoded_string_invalid_char,
            char_to_bits_map_example,
            # ... other args
            rep_color_huffman_rev_table_example,
            diff_value_huffman_rev_table_example,
            count_huffman_rev_table_example,
            representative_palette_indices_example,
            palette_size_example, image_width_example, image_height_example
        )
        print("Test Case 4 FAILED (error was expected).")
    except ValueError as e:
        print(f"Test Case 4 PASSED (expected error for invalid char): {e}")

    print("\n--- Test Case 5: Huffman code not found ---")
    # "BADH" -> "001000011111"
    # Decodes:
    # ((0,1),1) -> "0010"
    # ((0,0),2) -> "0001"
    # Next: rep_id=1 ("1"), then tries to decode diff_value from "11" (from "111")
    # "11" is not in diff_value_huffman_rev_table_example.
    encoded_string_huffman_fail = "BADH"
    try:
        pixel_indices = decode_image_data(
            encoded_string_huffman_fail,
            char_to_bits_map_example,
            # ... other args
            rep_color_huffman_rev_table_example,
            diff_value_huffman_rev_table_example,
            count_huffman_rev_table_example,
            representative_palette_indices_example,
            palette_size_example, image_width_example, image_height_example
        )
        print("Test Case 5 FAILED (error was expected).")
    except ValueError as e:
        print(f"Test Case 5 PASSED (expected error for huffman fail): {e}")