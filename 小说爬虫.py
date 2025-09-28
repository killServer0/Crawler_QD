import re
import time
import urllib.parse
import requests
from bs4 import BeautifulSoup


def build_http_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Connection": "keep-alive",
        }
    )
    return session


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]", "_", name)
    name = re.sub(r"\s+", " ", name)
    return name[:100] if len(name) > 100 else name


def fetch_faloo_free_chapters(session: requests.Session, url: str, limit: int = 10):
    response = session.get(url, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    chapter_list = soup.select(".DivTd3")
    total = min(limit, len(chapter_list)) if limit else len(chapter_list)
    success_count = 0

    for i in range(total):
        a = chapter_list[i].select_one("a")
        if not a:
            continue
        chapter_name = sanitize_filename(a.text)
        href = a.get("href") or ""
        if isinstance(href, list):
            href = href[0] if href else ""
        if href.startswith("//"):
            chapter_url = "https:" + href
        elif href.startswith("http"):
            chapter_url = href
        else:
            chapter_url = urllib.parse.urljoin(url, href)

        details_response = session.get(chapter_url, timeout=15)
        details_response.raise_for_status()
        details_soup = BeautifulSoup(details_response.text, "html.parser")
        p_list = details_soup.select(".noveContent>p")
        if not p_list:
            print(f"{chapter_name} -- 未找到内容，可能为付费或页面结构变更。")
            continue
        with open(chapter_name + ".txt", "a", encoding="utf-8") as file:
            for p in p_list:
                file.write(p.get_text(strip=False) + "\n")
        print(chapter_name + " -- 下载成功！")
        success_count += 1
        time.sleep(1)

    return success_count


def extract_qidian_chapter_links_from_info(session: requests.Session, info_url: str):
    # 直接从书籍信息页尝试抓取章节链接（仅限能在 HTML 中看到的免费章节）
    resp = session.get(info_url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    # 起点通常章节链接形如 //read.qidian.com/chapter/xxxx
    anchors = soup.select('a[href*="read.qidian.com/chapter/"]')
    links = []
    for a in anchors:
        href = a.get("href") or ""
        if isinstance(href, list):
            href = href[0] if href else ""
        text = a.get_text(strip=True)
        if not href:
            continue
        if href.startswith("//"):
            full = "https:" + href
        elif href.startswith("http"):
            full = href
        else:
            full = urllib.parse.urljoin(info_url, href)
        # 过滤可能的 VIP 阅读域名
        if "vipreader.qidian.com" in full:
            continue
        # 根据父级的可能 class 判断是否 VIP（保守过滤）
        parent_li = a.find_parent("li")
        if parent_li and ("vip" in (parent_li.get("class") or [])):
            continue
        links.append((text, full))
    # 去重并保持顺序
    seen = set()
    result = []
    for name, link in links:
        if link in seen:
            continue
        seen.add(link)
        result.append((name, link))
    return result


def fetch_qidian_chapter_content(session: requests.Session, chapter_url: str) -> list:
    # 读取章节正文（仅限免费章节）
    resp = session.get(chapter_url, timeout=15)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    content_container = soup.select_one(".read-content")
    if not content_container:
        return []
    ps = content_container.select("p")
    return [p.get_text(strip=False) for p in ps]


def fetch_qidian_free_from_url(session: requests.Session, url: str, limit: int = 10):
    parsed = urllib.parse.urlparse(url)
    netloc = parsed.netloc
    success_count = 0

    if "read.qidian.com" in netloc:
        # 单章链接
        paragraphs = fetch_qidian_chapter_content(session, url)
        if not paragraphs:
            print("该章节可能为付费章节或页面结构已变更。")
            return 0
        title = sanitize_filename("起点章节")
        with open(title + ".txt", "a", encoding="utf-8") as f:
            for line in paragraphs:
                f.write(line + "\n")
        print(title + " -- 下载成功！")
        return 1

    # 书籍信息页（尝试在 HTML 中直接拿到免费章节链接）
    chapters = extract_qidian_chapter_links_from_info(session, url)
    if not chapters:
        print(
            "未在信息页发现可直接访问的免费章节链接。起点目录常通过 JS 加载，脚本不抓取付费章节且不绕过反爬。"
        )
        return 0

    total = min(limit, len(chapters)) if limit else len(chapters)
    for i in range(total):
        chapter_name, chapter_url = chapters[i]
        chapter_name = sanitize_filename(chapter_name or f"chapter_{i + 1}")
        paragraphs = fetch_qidian_chapter_content(session, chapter_url)
        if not paragraphs:
            print(f"{chapter_name} -- 跳过（可能为付费或页面结构变更）。")
            continue
        with open(chapter_name + ".txt", "a", encoding="utf-8") as f:
            for line in paragraphs:
                f.write(line + "\n")
        print(chapter_name + " -- 下载成功！")
        success_count += 1
        time.sleep(1)

    return success_count


def check_paid_content_warning(session: requests.Session, url: str) -> bool:
    """检查页面是否包含付费内容警告"""
    try:
        response = session.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")

        # 检查常见的付费提示关键词
        paid_indicators = [
            "VIP",
            "付费",
            "订阅",
            "购买",
            "充值",
            "会员",
            "vip",
            "paid",
            "premium",
            "subscription",
        ]

        page_text = soup.get_text().lower()
        for indicator in paid_indicators:
            if indicator.lower() in page_text:
                return True
        return False
    except:
        return False


def save_reading_progress(book_title: str, chapter_count: int, success_count: int):
    """保存阅读进度到日志文件"""
    import datetime

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} - {book_title}: 尝试下载 {chapter_count} 章，成功 {success_count} 章\n"

    with open("reading_progress.log", "a", encoding="utf-8") as f:
        f.write(log_entry)


def create_reading_summary(book_title: str, chapters_info: list):
    """创建阅读摘要文件"""
    import datetime

    summary_file = f"{sanitize_filename(book_title)}_阅读摘要.txt"

    with open(summary_file, "w", encoding="utf-8") as f:
        f.write(f"《{book_title}》阅读摘要\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"下载时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"章节总数: {len(chapters_info)}\n\n")
        f.write("章节列表:\n")
        f.write("-" * 30 + "\n")

        for i, (name, status) in enumerate(chapters_info, 1):
            f.write(f"{i:3d}. {name} - {status}\n")

        f.write("\n注意: 本脚本仅下载免费章节，付费内容请通过官方渠道购买阅读。\n")
        f.write("支持正版，尊重版权！\n")


def main():
    print("=" * 60)
    print("小说爬取工具 v2.0")
    print("支持网站: 飞卢小说网、起点中文网（仅限免费章节）")
    print("=" * 60)

    # 将此处替换为目标书籍信息页或章节页（仅限免费内容）
    url = "https://b.faloo.com/1364176.html"

    # 用户输入URL（可选）
    user_url = input("请输入小说链接（直接回车使用默认链接）: ").strip()
    if user_url:
        url = user_url

    session = build_http_session()
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc

    # 检查是否包含付费内容
    if check_paid_content_warning(session, url):
        print("⚠️  警告: 检测到页面可能包含付费内容")
        print("本脚本仅支持免费章节，付费内容请通过官方渠道购买")
        choice = input("是否继续？(y/N): ").strip().lower()
        if choice != "y":
            print("已取消操作")
            return

    # 默认下载前 10 章，可修改为 None 下载可见全部
    limit = 10
    limit_input = input(
        f"请输入下载章节数量（直接回车下载前{limit}章，输入0下载全部）: "
    ).strip()
    if limit_input.isdigit():
        limit = int(limit_input) if int(limit_input) > 0 else None

    print(f"\n开始下载，目标: {url}")
    print(f"章节限制: {'全部' if limit is None else limit}章")
    print("-" * 60)

    chapters_info = []
    success_count = 0

    try:
        if "faloo.com" in host:
            success_count = fetch_faloo_free_chapters(session, url, limit=limit or 999)
        elif "qidian.com" in host:
            success_count = fetch_qidian_free_from_url(session, url, limit=limit or 999)
        else:
            print("暂不支持该站点，仅支持飞卢和起点（免费章节）。")
            return
    except Exception as e:
        print(f"下载过程中出现错误: {e}")
        return

    # 保存进度和摘要
    book_title = "未知书籍"
    try:
        response = session.get(url, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        title_elem = soup.select_one("title")
        if title_elem:
            book_title = title_elem.get_text().strip()
    except Exception:
        pass

    save_reading_progress(book_title, limit or 0, success_count)
    create_reading_summary(book_title, chapters_info)

    print("\n" + "=" * 60)
    print("下载完成！")
    print(f"成功下载: {success_count} 章")
    print("已生成阅读摘要文件")
    print("=" * 60)


if __name__ == "__main__":
    main()
