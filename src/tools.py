"""
🛠️ TOOL REGISTRY & SCHEMAS (Dành cho Role 2: Tool & Spec Engineer)
Nơi khai báo các công cụ (Tools) cho Agent "Trợ Lý Phân Tích Tính Cách & Chọn Quà Tặng".
Sử dụng SerpAPI Google Shopping Light để tra cứu sản phẩm trực tiếp từ Google Shopping.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()


def analyze_personality(behavior_description: str) -> str:
    """
    Phân tích mô tả tính cách, thói quen và sở thích người nhận quà.
    Trích xuất gu quà tặng phù hợp và đề xuất từ khóa (query) để tìm sản phẩm trên Google Shopping.
    
    Args:
        behavior_description (str): Mô tả về tính cách, thói quen, sở thích, tuổi tác, giới tính người nhận.
        
    Returns:
        str: Phân tích chân dung tính cách, gu quà tặng và danh sách từ khóa tìm kiếm Google Shopping gợi ý.
    """
    desc = behavior_description.lower()
    
    if any(k in desc for k in ["công nghệ", "game", "lập trình", "máy tính", "laptop", "macbook", "gadget"]):
        archetype = "TECH_MINIMALIST (Người yêu công nghệ & Tối giản)"
        search_queries = ["macbook", "tai nghe bluetooth", "bàn phím cơ không dây", "sạc dự phòng magsafe"]
        guidance = "Đồ công nghệ cao, thiết kế tối giản, ứng dụng thực tế."
    elif any(k in desc for k in ["sách", "vẽ", "nghệ thuật", "mộng mơ", "lãng mạn", "nến"]):
        archetype = "ARTISTIC_ROMANTIC (Tâm hồn nghệ sĩ & Lãng mạn)"
        search_queries = ["nến thơm cao cấp", "máy chụp ảnh polaroid", "bộ màu vẽ watercolor", "sổ tay bìa da"]
        guidance = "Giá trị tinh thần cao, thiết kế tinh tế, mang tính cá nhân hóa."
    elif any(k in desc for k in ["thể thao", "gym", "phượt", "du lịch", "năng động", "chạy bộ"]):
        archetype = "ACTIVE_EXPLORER (Người năng động & Thích trải nghiệm)"
        search_queries = ["đồng hồ thông minh thể thao", "bình giữ nhiệt 1l", "balo dã ngoại"]
        guidance = "Độ bền cao, phụ kiện thể thao, phục vụ hoạt động ngoài trời."
    else:
        archetype = "PRACTICAL_ELEGANT (Thực tế & Tinh tế)"
        search_queries = ["máy massage cổ vai", "bút ký kim loại", "bộ ly sứ quà tặng"]
        guidance = "Vật dụng thiết thực hàng ngày, chất lượng cao, tốt cho sức khỏe."
        
    return (
        f"📊 PHÂN TÍCH CHÂN DUNG TÍNH CÁCH:\n"
        f"- Nhóm tính cách: {archetype}\n"
        f"- Định hướng chọn quà: {guidance}\n"
        f"- Gợi ý từ khóa tìm kiếm Google Shopping: {', '.join(search_queries)}"
    )


def check_gift_stock_and_stores(query: str, min_price: int = None, max_price: int = None) -> str:
    """
    Tra cứu sản phẩm quà tặng trực tiếp từ Google Shopping thời gian thực qua SerpAPI (google_shopping_light).
    Trả về danh sách sản phẩm: Tên, Giá, Cửa hàng/Nguồn bán, Đánh giá, Vận chuyển và Link sản phẩm.
    
    Args:
        query (str): Từ khóa tìm kiếm sản phẩm quà tặng (VD: 'macbook', 'nến thơm cao cấp', 'tai nghe bluetooth').
        min_price (int, optional): Mức giá tối thiểu.
        max_price (int, optional): Mức giá tối đa.
        
    Returns:
        str: Kết quả sản phẩm thực tế từ Google Shopping kèm thông tin shop và giá tiền.
    """
    api_key = os.getenv("Search_API") or os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return "LỖI: Chưa cấu hình 'Search_API' hoặc 'SERPAPI_API_KEY' trong file .env."
    
    # Chuẩn bị tham số truy vấn SerpAPI Google Shopping Light
    search_params = {
        "engine": "google_shopping_light",
        "q": query,
        "hl": "en",
        "gl": "us"
    }
    if min_price is not None:
        search_params["min_price"] = min_price
    if max_price is not None:
        search_params["max_price"] = max_price

    shopping_results = []
    
    # 1. Thử dùng SDK serpapi client chính thức
    try:
        import serpapi
        client = serpapi.Client(api_key=api_key)
        results = client.search(search_params)
        shopping_results = results.get("shopping_results", [])
    except ImportError:
        # 2. Fallback dùng requests gọi trực tiếp API SerpAPI nếu chưa cài package serpapi
        endpoint_url = "https://serpapi.com/search?engine=google_shopping_light"
        search_params["api_key"] = api_key
        try:
            resp = requests.get(endpoint_url, params=search_params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                shopping_results = data.get("shopping_results", [])
            else:
                return f"LỖI gọi SerpAPI HTTP {resp.status_code}: {resp.text}"
        except Exception as err:
            return f"LỖI kết nối SerpAPI: {str(err)}"
    except Exception as e:
        return f"LỖI thực thi SerpAPI Search: {str(e)}"

    if not shopping_results:
        return f"Không tìm thấy sản phẩm nào trên Google Shopping cho từ khóa '{query}'."

    # Extract và format kết quả shopping_results
    output = [f"🛍️ KẾT QUẢ GOOGLE SHOPPING CHO TỪ KHÓA '{query}':"]
    for idx, item in enumerate(shopping_results[:5], 1):
        title = item.get("title", "N/A")
        price = item.get("price", "N/A")
        source = item.get("source", "N/A")
        rating = item.get("rating", "N/A")
        reviews = item.get("reviews", "")
        delivery = item.get("delivery", "")
        product_link = item.get("product_link", "N/A")
        
        info = f"{idx}. {title}\n   - Giá: {price}\n   - Nguồn/Cửa hàng: {source}"
        if rating != "N/A":
            info += f"\n   - Đánh giá: {rating}⭐ ({reviews} nhận xét)"
        if delivery:
            info += f"\n   - Vận chuyển: {delivery}"
        if product_link != "N/A":
            info += f"\n   - Link: {product_link}"
            
        output.append(info)

    return "\n\n".join(output)


def generate_greeting_card(relationship: str, occasion: str, personality_style: str) -> str:
    """
    Tạo câu chúc thiệp cá nhân hóa phù hợp với tính cách người nhận và dịp tặng.
    
    Args:
        relationship (str): Mối quan hệ với người nhận (VD: 'Bạn thân', 'Người yêu', 'Đồng nghiệp').
        occasion (str): Dịp tặng quà (VD: 'Sinh nhật', 'Kỷ niệm', 'Tốt nghiệp').
        personality_style (str): Phong cách lời chúc (VD: 'Tối giản', 'Lãng mạn', 'Hài hước', 'Trang trọng').
        
    Returns:
        str: Mẫu lời chúc viết thiệp hoàn chỉnh.
    """
    return (
        f"📝 [MẪU THIỆP GỢI Ý - Phong cách: {personality_style}]\n"
        f"Gửi: {relationship} | Dịp: {occasion}\n"
        f"\"Chúc {relationship} một ngày {occasion} thật ý nghĩa và trọn vẹn! "
        f"Hy vọng món quà này sẽ mang lại thêm nhiều niềm vui và đồng hành cùng bạn trong những hành trình sắp tới. ✨\""
    )


# Đăng ký danh sách các tool khả dụng cho ReAct Agent
AVAILABLE_TOOLS = {
    "analyze_personality": analyze_personality,
    "check_gift_stock_and_stores": check_gift_stock_and_stores,
    "generate_greeting_card": generate_greeting_card,
}
