import struct
import os
from PIL import Image

def apply_skin(png_path, blob_path):
    if not os.path.exists(png_path):
        print(f"Lỗi: Không tìm thấy file ảnh {png_path}")
        return

    if not os.path.exists(blob_path):
        print(f"Lỗi: Không tìm thấy file {blob_path}")
        return

    # Mở và chuyển đổi ảnh sang RGBA
    img = Image.open(png_path).convert("RGBA")
    width, height = img.size

    if (width, height) not in [(64, 32), (64, 64)]:
        print(f"Lỗi: Kích thước ảnh không hợp lệ ({width}x{height}). Phải là 64x32 hoặc 64x64.")
        return

    print(f"Đang xử lý skin {width}x{height}...")
    
    # Lấy dữ liệu byte thô
    skin_data = img.tobytes()

    # Đọc blob hiện tại
    with open(blob_path, "rb") as f:
        blob = f.read()

    # Tìm vị trí "Standard_Custom" (tên loại skin thường dùng trong Minebot)
    # Skin data thường nằm ngay sau độ dài và chuỗi "Standard_Custom"
    skin_name = b"Standard_Custom"
    name_pos = blob.find(skin_name)
    
    if name_pos == -1:
        print("Lỗi: Không tìm thấy cấu trúc skin trong blob!")
        return

    # Cấu trúc: [2 bytes length skin_name] [skin_name] [2 bytes length skin_data] [skin_data]
    # Độ dài skin data nằm ở ngay sau "Standard_Custom"
    length_pos = name_pos + len(skin_name)
    
    # Tạo blob mới
    # Phần đầu giữ nguyên đến hết tên skin
    new_blob = blob[:length_pos]
    # Thêm độ dài mới của skin data (2 bytes Big Endian)
    new_blob += struct.pack(">H", len(skin_data))
    # Thêm dữ liệu skin mới
    new_blob += skin_data

    # Ghi lại vào file
    with open(blob_path, "wb") as f:
        f.write(new_blob)

    print(f"Đã cập nhật skin thành công vào {blob_path}!")

if __name__ == "__main__":
    # Thay 'myskin.png' bằng đường dẫn đến file skin của bạn
    apply_skin("skin.png", "minebot_python/login_blob.bin")
