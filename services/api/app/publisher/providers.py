import json
import os
import threading
import time
from pathlib import Path
from typing import Protocol

from .models import (
    PLATFORM_LOGIN_URLS,
    PLATFORM_PUBLISH_URLS,
    PublishJob,
    PublishJobStatus,
    PublisherAccount,
    PublisherAccountStatus,
    PublisherPlatform,
    publisher_screenshot_path,
    publisher_state_path,
    utc_now,
)
from .store import publisher_store


_login_session_lock = threading.Lock()
_active_login_sessions: set[str] = set()


class PublisherProvider(Protocol):
    def login(self, account: PublisherAccount, timeout_seconds: int) -> PublisherAccount:
        ...

    def check_session(self, account: PublisherAccount) -> PublisherAccount:
        ...

    def publish(self, account: PublisherAccount, job: PublishJob) -> PublishJob:
        ...

    def query_result(self, job: PublishJob) -> PublishJob:
        ...


class OfficialApiPublisherProvider:
    """Minimal official-API adapter shell.

    The real Douyin/Kuaishou API credentials and upload endpoints are business
    approval dependent, so this adapter validates configuration and records a
    precise handoff instead of pretending to publish without credentials.
    """

    def login(self, account: PublisherAccount, timeout_seconds: int) -> PublisherAccount:
        account.status = PublisherAccountStatus.needs_user_action
        account.error_message = "官方 API 账号需要先完成平台 OAuth 授权。"
        account.updated_at = utc_now()
        return publisher_store.put_account(account)

    def check_session(self, account: PublisherAccount) -> PublisherAccount:
        token = _official_token(account.platform)
        account.last_checked_at = utc_now()
        account.updated_at = utc_now()
        if token:
            account.status = PublisherAccountStatus.logged_in
            account.error_message = None
        else:
            account.status = PublisherAccountStatus.needs_login
            account.error_message = "未配置官方 API access token，将使用 RPA 发布兜底。"
        return publisher_store.put_account(account)

    def publish(self, account: PublisherAccount, job: PublishJob) -> PublishJob:
        token = _official_token(account.platform)
        if not token:
            job.status = PublishJobStatus.needs_user_action
            job.error_message = "未配置官方 API access token，无法通过官方 API 发布。"
            job.logs.append("official_api_missing_token")
            job.updated_at = utc_now()
            return publisher_store.put_job(job)

        # Keep this intentionally conservative. Upload protocols differ by
        # platform and approval scope; callers can replace this branch once
        # platform credentials are available.
        job.status = PublishJobStatus.needs_user_action
        job.error_message = "官方 API 凭证已配置，但上传/发布端点尚未绑定到业务应用。"
        job.logs.append("official_api_configured_no_endpoint_binding")
        job.updated_at = utc_now()
        return publisher_store.put_job(job)

    def query_result(self, job: PublishJob) -> PublishJob:
        return job


class RpaPublisherProvider:
    def login(self, account: PublisherAccount, timeout_seconds: int) -> PublisherAccount:
        with _login_session_lock:
            if account.account_id in _active_login_sessions:
                account.status = PublisherAccountStatus.login_opened
                account.error_message = "登录窗口已打开，请在现有浏览器窗口中完成扫码或验证。"
                account.updated_at = utc_now()
                return publisher_store.put_account(account)
            _active_login_sessions.add(account.account_id)
        account.status = PublisherAccountStatus.login_opened
        account.error_message = "已打开浏览器登录窗口，请扫码/验证后保持页面登录状态。"
        account.updated_at = utc_now()
        publisher_store.put_account(account)
        if _playwright_disabled():
            with _login_session_lock:
                _active_login_sessions.discard(account.account_id)
            account.status = PublisherAccountStatus.needs_user_action
            account.error_message = "当前环境禁用了 Playwright，可在本机运行后重新登录。"
            account.updated_at = utc_now()
            return publisher_store.put_account(account)
        threading.Thread(
            target=_open_login_window,
            args=(account.account_id, timeout_seconds),
            daemon=True,
        ).start()
        return account

    def check_session(self, account: PublisherAccount) -> PublisherAccount:
        account.last_checked_at = utc_now()
        account.updated_at = utc_now()
        if _profile_has_state(account):
            account.status = PublisherAccountStatus.logged_in
            account.error_message = None
        else:
            account.status = PublisherAccountStatus.needs_login
            account.error_message = "未检测到该账号的浏览器登录态，请先登录。"
        return publisher_store.put_account(account)

    def publish(self, account: PublisherAccount, job: PublishJob) -> PublishJob:
        if not Path(job.video_path).exists():
            job.status = PublishJobStatus.failed
            job.error_message = "待发布视频文件不存在。"
            job.updated_at = utc_now()
            return publisher_store.put_job(job)

        account = self.check_session(account)
        if account.status != PublisherAccountStatus.logged_in:
            job.status = PublishJobStatus.needs_user_action
            job.error_message = "账号未登录，请先完成登录后重试发布。"
            job.logs.append("account_not_logged_in")
            job.updated_at = utc_now()
            return publisher_store.put_job(job)

        if _playwright_disabled():
            job.status = PublishJobStatus.needs_user_action
            job.error_message = "当前环境禁用了 Playwright，未执行真实上传。"
            job.logs.append("playwright_disabled")
            job.updated_at = utc_now()
            return publisher_store.put_job(job)

        return _publish_with_playwright(account, job)

    def query_result(self, job: PublishJob) -> PublishJob:
        return job


def get_provider(account: PublisherAccount) -> PublisherProvider:
    if account.provider == "official_api":
        checked = OfficialApiPublisherProvider().check_session(account)
        if checked.status == PublisherAccountStatus.logged_in:
            return OfficialApiPublisherProvider()
    return RpaPublisherProvider()


def _official_token(platform: PublisherPlatform) -> str:
    names = {
        PublisherPlatform.douyin: "DOUYIN_OPEN_ACCESS_TOKEN",
        PublisherPlatform.kuaishou: "KUAISHOU_OPEN_ACCESS_TOKEN",
        PublisherPlatform.xiaohongshu: "XIAOHONGSHU_OPEN_ACCESS_TOKEN",
        PublisherPlatform.shipinhao: "SHIPINHAO_OPEN_ACCESS_TOKEN",
    }
    return os.getenv(names[platform], "").strip()


def _playwright_disabled() -> bool:
    return os.getenv("PUBLISHER_DISABLE_PLAYWRIGHT", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _profile_has_state(account: PublisherAccount) -> bool:
    profile = Path(account.profile_dir)
    state = Path(account.storage_state_path)
    if _storage_state_has_cookies(account):
        return True
    cookie_files = list(profile.glob("**/Cookies")) if profile.exists() else []
    return any(path.is_file() and path.stat().st_size > 0 for path in cookie_files)


def _storage_state_has_cookies(account: PublisherAccount) -> bool:
    state = Path(account.storage_state_path)
    if not state.exists():
        return False
    try:
        data = json.loads(state.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    cookies = data.get("cookies") if isinstance(data, dict) else None
    return isinstance(cookies, list) and len(cookies) > 0


def _save_browser_state(context, account: PublisherAccount) -> None:
    try:
        context.storage_state(path=account.storage_state_path)
    except Exception:
        pass


def _apply_login_context_init_scripts(context, platform: PublisherPlatform) -> None:
    if platform != PublisherPlatform.kuaishou:
        return
    try:
        context.add_init_script(
            """
            (() => {
              try {
                Object.defineProperty(navigator, 'webdriver', {
                  get: () => undefined,
                  configurable: true,
                });
              } catch (_) {}
              try {
                window.chrome = window.chrome || { runtime: {} };
              } catch (_) {}
            })();
            """
        )
    except Exception:
        pass


def _open_login_window(account_id: str, timeout_seconds: int) -> None:
    from playwright.sync_api import sync_playwright

    account = publisher_store.get_account(account_id)
    login_url = PLATFORM_LOGIN_URLS[account.platform]
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                account.profile_dir,
                headless=False,
                args=["--deny-permission-prompts"],
                viewport=_browser_viewport(account.platform),
            )
            _apply_login_context_init_scripts(context, account.platform)
            page = _prepare_single_page(context)
            page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            deadline = time.monotonic() + timeout_seconds
            detected_login = False
            while time.monotonic() < deadline:
                page = _active_page(context, page)
                if page is None:
                    break
                _save_browser_state(context, account)
                if _looks_logged_in(page, account.platform):
                    detected_login = True
                    account.status = PublisherAccountStatus.logged_in
                    account.error_message = None
                    nickname = _extract_account_nickname(page, account.platform)
                    if nickname:
                        account.nickname = nickname
                    account.updated_at = utc_now()
                    publisher_store.put_account(account)
                    page.wait_for_timeout(1500)
                    _save_browser_state(context, account)
                    break
                page.wait_for_timeout(5000)
            _save_browser_state(context, account)
            if _active_page(context, page) is not None:
                context.close()
        if detected_login or account.status == PublisherAccountStatus.logged_in:
            account.status = PublisherAccountStatus.logged_in
            account.error_message = None
        elif _storage_state_has_cookies(account):
            account.status = PublisherAccountStatus.needs_user_action
            account.error_message = "已保存浏览器状态，但未确认进入发布后台；请点击检测或重新登录。"
        else:
            account.status = PublisherAccountStatus.needs_login
            account.error_message = "未保存到有效登录态，请重新打开登录窗口并完成平台登录。"
    except Exception as exc:
        account.status = PublisherAccountStatus.failed
        account.error_message = f"登录窗口启动失败：{exc}"
    finally:
        with _login_session_lock:
            _active_login_sessions.discard(account_id)
    account.updated_at = utc_now()
    publisher_store.put_account(account)


def _active_page(context, current_page):
    if current_page is not None and not current_page.is_closed():
        return current_page
    for page in context.pages:
        if not page.is_closed():
            return page
    return None


def _browser_viewport(platform: PublisherPlatform) -> dict[str, int]:
    if platform == PublisherPlatform.xiaohongshu:
        return {"width": 1920, "height": 1080}
    return {"width": 1360, "height": 900}


def _apply_platform_page_zoom(page, platform: PublisherPlatform) -> None:
    if platform != PublisherPlatform.xiaohongshu:
        return
    # XHS now exposes the bottom publish action at 100% zoom. Keeping a forced
    # CSS zoom changes DOM coordinates and can make RPA clicks hit nearby
    # controls such as the scheduled-publish switch.
    return


def _looks_logged_in(page, platform: PublisherPlatform) -> bool:
    if _looks_like_login_page(page):
        return False
    platform_texts = {
        PublisherPlatform.douyin: ["作品描述", "设置封面", "发布设置", "发布作品"],
        PublisherPlatform.kuaishou: ["发布视频", "作品标题", "选择封面", "存草稿"],
        PublisherPlatform.xiaohongshu: ["上传视频", "发布笔记", "添加标题", "添加正文"],
        PublisherPlatform.shipinhao: ["发表动态", "上传视频", "视频描述", "声明原创"],
    }
    if any(_is_text_visible(page, text) for text in platform_texts[platform]):
        return True
    try:
        return page.locator("input[type=file]").first.is_visible(timeout=500)
    except Exception:
        return False


def _looks_like_login_page(page) -> bool:
    login_texts = [
        "手机号登录",
        "验证码登录",
        "扫码登录",
        "微信扫码",
        "登录/注册",
        "请输入手机号",
        "请输入验证码",
        "账号登录",
        "密码登录",
    ]
    if any(_is_text_visible(page, text) for text in login_texts):
        return True
    try:
        return page.locator("input[type=password]").first.is_visible(timeout=500)
    except Exception:
        return False


def _extract_account_nickname(page, platform: PublisherPlatform) -> str | None:
    if platform == PublisherPlatform.xiaohongshu:
        nickname = _extract_xiaohongshu_nickname(page)
        if nickname:
            return nickname
    selectors = [
        "[class*='nickname']",
        "[class*='Nickname']",
        "[class*='user-name']",
        "[class*='username']",
        "[class*='UserName']",
        "[class*='account-name']",
        "[class*='AccountName']",
        "[class*='name']",
    ]
    blocked = {
        "发布",
        "首页",
        "通知",
        "内容管理",
        "作品管理",
        "创作中心",
        "数据中心",
        "登录",
        "扫码登录",
        "创作服务平台",
        "小红书创作服务平台",
        "小红书",
        "发布笔记",
    }
    for selector in selectors:
        try:
            texts = page.locator(selector).all_inner_texts()
        except Exception:
            continue
        for text in texts:
            candidate = " ".join(text.split()).strip()
            if 1 < len(candidate) <= 30 and candidate not in blocked:
                return candidate
    try:
        title = page.title()
    except Exception:
        return None
    title = title.replace("抖音创作者中心", "").replace("快手创作者服务平台", "").replace("小红书创作服务平台", "").strip(" -_|")
    return title if 1 < len(title) <= 30 and title not in blocked else None


def _extract_xiaohongshu_nickname(page) -> str | None:
    try:
        return page.evaluate(
            """
            () => {
              const blocked = new Set([
                '小红书', '创作服务平台', '小红书创作服务平台', '发布笔记',
                '首页', '笔记管理', '数据看板', '活动中心', '创作学院',
                '创作百科', '笔记灵感', '智能标题'
              ]);
              const clean = (text) => (text || '').replace(/\\s+/g, ' ').trim();
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  rect.width > 0 &&
                  rect.height > 0;
              };
              const candidates = Array.from(document.querySelectorAll('body *'))
                .filter(isVisible)
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const text = clean(el.innerText || el.textContent);
                  return { text, x: rect.x, y: rect.y, width: rect.width, height: rect.height };
                })
                .filter((item) =>
                  item.x > window.innerWidth * 0.72 &&
                  item.y < 260 &&
                  item.text.length >= 2 &&
                  item.text.length <= 24 &&
                  !blocked.has(item.text) &&
                  !/发布|首页|管理|数据|活动|学院|百科|预览|封面|礼物|智能|平台/.test(item.text)
                )
                .sort((a, b) => {
                  const ay = Math.abs(a.y - 150);
                  const by = Math.abs(b.y - 150);
                  return ay - by || a.text.length - b.text.length;
                });
              return candidates[0]?.text || null;
            }
            """
        )
    except Exception:
        return None


def _publish_with_playwright(account: PublisherAccount, job: PublishJob) -> PublishJob:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    publish_url = PLATFORM_PUBLISH_URLS[account.platform]
    job.status = PublishJobStatus.running
    job.error_message = None
    job.logs.append(f"open:{publish_url}")
    job.updated_at = utc_now()
    publisher_store.put_job(job)
    mode = "draft" if job.publish_mode == "draft" else "direct"
    clicked = False
    confirmed = False
    manual_verification = False

    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                account.profile_dir,
                headless=False,
                args=["--deny-permission-prompts"],
                viewport=_browser_viewport(account.platform),
            )
            _apply_login_context_init_scripts(context, account.platform)
            page = _prepare_single_page(context)
            page.goto(publish_url, wait_until="domcontentloaded", timeout=60000)
            _apply_platform_page_zoom(page, account.platform)
            page.wait_for_timeout(3000)
            file_input = page.locator("input[type=file]").first
            try:
                file_input.set_input_files(job.video_path, timeout=15000)
                job.logs.append("video_file_selected")
            except PlaywrightTimeoutError:
                job.status = PublishJobStatus.needs_user_action
                job.error_message = "未找到上传控件，平台可能要求重新登录或验证；浏览器窗口已保留，请处理后等待系统继续。"
                job.logs.append("upload_input_not_found_waiting_user")
                _capture_job_screenshot(page, job)
                _save_browser_state(context, account)
                job.updated_at = utc_now()
                publisher_store.put_job(job)
                if not _wait_for_upload_control(page, context, account, job, account.platform, publish_url):
                    context.close()
                    return publisher_store.put_job(job)
                file_input = page.locator("input[type=file]").first
                file_input.set_input_files(job.video_path, timeout=15000)
                job.logs.append("video_file_selected_after_user_action")

            if account.platform == PublisherPlatform.xiaohongshu:
                _fill_xiaohongshu_fields(
                    page,
                    job.title,
                    _compose_xiaohongshu_description(job.body, job.topics),
                    job,
                )
            elif account.platform == PublisherPlatform.shipinhao:
                _wait_for_shipinhao_form_ready(page, job)
                _fill_shipinhao_fields(
                    page,
                    job.title,
                    _compose_shipinhao_description(job.title, job.body, job.topics),
                    job,
                )
            else:
                _best_effort_fill(page, account.platform, job.title, job.body.strip())
                _best_effort_add_topics(page, account.platform, job.topics, job)
            _wait_for_upload_ready(page, job)
            clicked = _best_effort_click_action(page, mode, account.platform, job)
            if clicked:
                job.logs.append(
                    "draft_button_clicked" if mode == "draft" else "publish_button_clicked"
                )
                _best_effort_click_confirm(page)
            confirmed = False
            if clicked:
                manual_verification = True
                job.status = PublishJobStatus.needs_user_action
                job.error_message = (
                    "已点击保存草稿按钮，浏览器窗口会保留等待平台保存成功；如出现短信/验证码，请在窗口中完成。"
                    if mode == "draft"
                    else "已点击发布按钮，浏览器窗口会保留等待平台发布成功；如出现短信/验证码，请在窗口中完成。"
                )
                job.logs.append("manual_confirmation_wait_started")
                _capture_job_screenshot(page, job)
                _save_browser_state(context, account)
                job.updated_at = utc_now()
                publisher_store.put_job(job)
                confirmed = _wait_for_manual_action_result(page, context, account, job, mode)
            elif account.platform == PublisherPlatform.xiaohongshu:
                manual_verification = True
                job.status = PublishJobStatus.needs_user_action
                job.error_message = "视频和文案已填入，但未能自动点击发布按钮；浏览器窗口已保留，请手动点击底部红色发布按钮。"
                job.logs.append("manual_publish_wait_started")
                _capture_job_screenshot(page, job)
                _save_browser_state(context, account)
                job.updated_at = utc_now()
                publisher_store.put_job(job)
                confirmed = _wait_for_manual_action_result(page, context, account, job, mode)
                if confirmed:
                    clicked = True
                    job.logs.append("manual_publish_completed")
            _capture_job_screenshot(page, job)
            _save_browser_state(context, account)
            context.close()

        if clicked and confirmed and mode == "draft":
            job.status = PublishJobStatus.drafted
            job.error_message = None
        elif clicked and confirmed:
            job.status = PublishJobStatus.published
            job.error_message = None
        elif clicked:
            job.status = PublishJobStatus.needs_user_action
            job.error_message = (
                "已点击保存草稿按钮，但平台仍在等待短信/验证码或未返回保存成功提示，请人工确认。"
                if mode == "draft"
                else "已点击发布按钮，但平台仍在等待短信/验证码或未返回发布成功提示，请人工确认。"
            ) if manual_verification else (
                "已点击保存草稿按钮，但未检测到平台保存成功提示，请在打开的发布页面确认结果。"
                if mode == "draft"
                else "已点击发布按钮，但未检测到平台发布成功或审核中提示，请在打开的发布页面确认结果。"
            )
            job.logs.append("action_result_not_confirmed")
        else:
            job.status = PublishJobStatus.needs_user_action
            job.error_message = (
                "视频和文案已尽量填入，未能稳定识别保存草稿按钮，请人工确认。"
                if mode == "draft"
                else "视频和文案已尽量填入，未能稳定识别发布按钮，请人工确认。"
            )
            job.logs.append("action_button_not_found")
    except Exception as exc:
        job.status = PublishJobStatus.failed
        job.error_message = f"RPA 发布失败：{exc}"
        job.logs.append("rpa_exception")
    job.updated_at = utc_now()
    return publisher_store.put_job(job)


def _compose_publish_text(job: PublishJob) -> str:
    topic_text = " ".join(f"#{topic.lstrip('#')}" for topic in job.topics if topic.strip())
    return " ".join(part for part in [job.body.strip(), topic_text] if part)


def _compose_xiaohongshu_description(body: str, topics: list[str]) -> str:
    clean_body = body.strip()
    clean_topics = []
    for topic in topics:
        clean = topic.strip().lstrip("#").strip()
        if clean and clean not in clean_topics:
            clean_topics.append(clean)
    topic_text = " ".join(f"#{topic}" for topic in clean_topics)
    return " ".join(part for part in [clean_body, topic_text] if part)


def _compose_shipinhao_description(title: str, body: str, topics: list[str]) -> str:
    clean_title = title.strip()
    clean_body = body.strip()
    clean_topics = []
    for topic in topics:
        clean = topic.strip().lstrip("#").strip()
        if clean and clean not in clean_topics:
            clean_topics.append(clean)
    topic_text = " ".join(f"#{topic}" for topic in clean_topics)
    if clean_title and clean_title not in clean_body:
        return "\n".join(part for part in [clean_title, clean_body, topic_text] if part)
    return "\n".join(part for part in [clean_body, topic_text] if part)


def _prepare_single_page(context):
    page = context.pages[0] if context.pages else context.new_page()
    for extra_page in context.pages[1:]:
        try:
            extra_page.close()
        except Exception:
            pass
    try:
        page.bring_to_front()
    except Exception:
        pass
    return page


def _best_effort_fill(page, platform: PublisherPlatform, title: str, body: str) -> None:
    if platform == PublisherPlatform.xiaohongshu:
        _fill_xiaohongshu_fields(page, title, body, None)
        return
    if platform == PublisherPlatform.shipinhao:
        _fill_shipinhao_fields(page, title, body, None)
        return
    textareas = page.locator("textarea")
    inputs = page.locator("input[type=text], input:not([type])")
    editable = page.locator("[contenteditable=true]")
    for locator, value in ((inputs.first, title), (textareas.first, body), (editable.first, body)):
        if not value:
            continue
        try:
            locator.fill(value, timeout=5000)
        except Exception:
            try:
                locator.click(timeout=3000)
                locator.type(value, delay=15, timeout=10000)
            except Exception:
                pass


def _wait_for_shipinhao_form_ready(page, job: PublishJob | None = None) -> None:
    deadline_ms = 90000
    elapsed = 0
    while elapsed < deadline_ms:
        if _shipinhao_editor_available(page):
            if job is not None:
                job.logs.append("shipinhao_form_ready")
            return
        busy = any(_is_text_visible(page, text) for text in ["上传中", "处理中", "转码中", "视频处理中"])
        if not busy and elapsed >= 12000:
            break
        page.wait_for_timeout(2000)
        elapsed += 2000
    if job is not None:
        job.logs.append("shipinhao_form_ready_timeout")


def _shipinhao_editor_available(page) -> bool:
    try:
        if any(_is_text_visible(page, text) for text in ["视频描述", "短标题", "修改描述和封面"]):
            return True
        return bool(
            page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                      style.visibility !== 'hidden' &&
                      rect.width > 120 &&
                      rect.height > 24;
                  };
                  return Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"]'))
                    .some((el) => {
                      if (!isVisible(el)) return false;
                      const hint = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('data-placeholder') || '',
                        el.getAttribute('aria-label') || '',
                        el.className || '',
                        el.parentElement?.innerText || '',
                      ].join(' ');
                      return /描述|视频描述|说点什么|发表动态|正文|标题|请输入/.test(hint);
                    });
                }
                """
            )
        )
    except Exception:
        return False


def _fill_shipinhao_fields(
    page,
    title: str,
    description: str,
    job: PublishJob | None,
) -> None:
    filled_title = False
    if title:
        filled_title = _fill_first_matching(
            page,
            [
                "input[placeholder*='标题']",
                "textarea[placeholder*='标题']",
                "[contenteditable=true][data-placeholder*='标题']",
                "[contenteditable=true][placeholder*='标题']",
            ],
            title,
        )
    filled_description = False
    if description:
        filled_description = _fill_first_matching(
            page,
            [
                "textarea[placeholder*='描述']",
                "textarea[placeholder*='说点什么']",
                "textarea[placeholder*='正文']",
                "textarea[placeholder*='请输入']",
                "[contenteditable=true][data-placeholder*='描述']",
                "[contenteditable=true][data-placeholder*='说点什么']",
                "[contenteditable=true][data-placeholder*='正文']",
                "[contenteditable=true][data-placeholder*='请输入']",
                "[contenteditable=true][placeholder*='描述']",
                "[contenteditable=true][placeholder*='说点什么']",
            ],
            description,
        )
        if not filled_description:
            filled_description = _fill_shipinhao_description_fallback(page, description)
        if not filled_description:
            filled_description = _fill_shipinhao_description_by_label(page, description)
    if job is not None:
        job.logs.append("shipinhao_title_filled" if filled_title else "shipinhao_title_not_found")
        job.logs.append(
            "shipinhao_description_filled"
            if filled_description
            else "shipinhao_description_fill_failed"
        )


def _fill_shipinhao_description_fallback(page, description: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (description) => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                      style.visibility !== 'hidden' &&
                      rect.width > 120 &&
                      rect.height > 24 &&
                      rect.top >= 0 &&
                      rect.left >= 0;
                  };
                  const setValue = (el) => {
                    el.scrollIntoView({ block: 'center', inline: 'center' });
                    el.focus();
                    if ('value' in el) {
                      const setter = Object.getOwnPropertyDescriptor(el.__proto__, 'value')?.set;
                      if (setter) setter.call(el, description);
                      else el.value = description;
                    } else {
                      el.innerText = description;
                      el.textContent = description;
                    }
                    el.dispatchEvent(new InputEvent('input', {
                      bubbles: true,
                      cancelable: true,
                      inputType: 'insertText',
                      data: description,
                    }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true }));
                  };
                  const blocked = /搜索|链接|位置|地址|时间|日期|封面|合集|分类|声明|原创|权限/;
                  const candidates = Array.from(document.querySelectorAll('textarea,input,[contenteditable="true"]'))
                    .filter(isVisible)
                    .map((el, index) => {
                      const rect = el.getBoundingClientRect();
                      const hint = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('data-placeholder') || '',
                        el.getAttribute('aria-label') || '',
                        el.className || '',
                        el.parentElement?.innerText || '',
                      ].join(' ');
                      let score = rect.width + rect.height + index;
                      if (/描述|视频描述|说点什么|发表动态|正文|请输入/.test(hint)) score += 10000;
                      if (/标题/.test(hint)) score -= 1000;
                      if (blocked.test(hint)) score -= 10000;
                      if (rect.height > 80) score += 2000;
                      return { el, score, hint };
                    })
                    .sort((a, b) => b.score - a.score);
                  const target = candidates[0]?.el;
                  if (!target || candidates[0].score < 0) return false;
                  setValue(target);
                  return true;
                }
                """,
                description,
            )
        )
    except Exception:
        return False


def _fill_shipinhao_description_by_label(page, description: str) -> bool:
    """Fill the Channels description editor by clicking near the visible label.

    The Channels editor used after upload can be a custom rich-text surface
    without placeholder/contenteditable attributes. The stable anchor on that
    page is the left-side "视频描述" label.
    """
    try:
        target = page.evaluate(
            """
            () => {
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  rect.width > 0 &&
                  rect.height > 0 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  rect.top < window.innerHeight &&
                  rect.left < window.innerWidth;
              };
              const labels = Array.from(document.querySelectorAll('body *'))
                .filter(isVisible)
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                  return { el, rect, text };
                })
                .filter((item) =>
                  item.text === '视频描述' ||
                  (item.text.includes('视频描述') && item.text.length <= 12)
                )
                .sort((a, b) => a.rect.left - b.rect.left || a.rect.top - b.rect.top);
              const label = labels[0];
              if (!label) return null;
              return {
                x: Math.min(window.innerWidth - 80, label.rect.right + 220),
                y: Math.min(window.innerHeight - 80, label.rect.top + Math.max(80, label.rect.height / 2)),
                labelX: label.rect.left,
                labelY: label.rect.top,
              };
            }
            """
        )
        if not target:
            return False
        page.mouse.click(float(target["x"]), float(target["y"]))
        page.wait_for_timeout(300)
        try:
            page.keyboard.press("Control+A")
            page.wait_for_timeout(100)
        except Exception:
            pass
        page.keyboard.type(description, delay=12, timeout=30000)
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def _fill_xiaohongshu_fields(
    page,
    title: str,
    description: str,
    job: PublishJob | None,
) -> None:
    if title:
        filled_title = _fill_first_matching(
            page,
            [
                "input[placeholder*='标题']",
                "textarea[placeholder*='标题']",
                "[contenteditable=true][data-placeholder*='标题']",
                "[contenteditable=true][placeholder*='标题']",
            ],
            title,
        )
        if job is not None:
            job.logs.append("xhs_title_filled" if filled_title else "xhs_title_fill_failed")
    if description:
        filled_description = _fill_first_matching(
            page,
            [
                "textarea[placeholder*='正文']",
                "textarea[placeholder*='描述']",
                "textarea[placeholder*='分享']",
                "textarea[placeholder*='简介']",
                "textarea[placeholder*='说点什么']",
                "[contenteditable=true][data-placeholder*='正文']",
                "[contenteditable=true][data-placeholder*='描述']",
                "[contenteditable=true][data-placeholder*='简介']",
                "[contenteditable=true][data-placeholder*='说点什么']",
                "[contenteditable=true][placeholder*='正文']",
                "[contenteditable=true][placeholder*='描述']",
            ],
            description,
        )
        if not filled_description:
            filled_description = _fill_xiaohongshu_description_fallback(page, description)
        if job is not None:
            job.logs.append(
                "xhs_description_filled"
                if filled_description
                else "xhs_description_fill_failed"
            )


def _fill_xiaohongshu_description_fallback(page, description: str) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (description) => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.visibility !== 'hidden' &&
                      style.display !== 'none' &&
                      rect.width > 80 &&
                      rect.height > 40;
                  };
                  const candidates = Array.from(
                    document.querySelectorAll('textarea,[contenteditable="true"]')
                  ).filter(isVisible);
                  const scored = candidates
                    .map((el, index) => {
                      const rect = el.getBoundingClientRect();
                      const hint = [
                        el.getAttribute('placeholder') || '',
                        el.getAttribute('data-placeholder') || '',
                        el.getAttribute('aria-label') || '',
                        el.className || '',
                      ].join(' ');
                      let score = rect.width + rect.height + index;
                      if (/标题/.test(hint)) score -= 10000;
                      if (/正文|描述|简介|分享|说点什么/.test(hint)) score += 10000;
                      if (rect.height > 120) score += 5000;
                      return { el, score };
                    })
                    .sort((a, b) => b.score - a.score);
                  const target = scored[0]?.el;
                  if (!target) return false;
                  target.focus();
                  if ('value' in target) {
                    target.value = description;
                  } else {
                    target.innerText = description;
                  }
                  target.dispatchEvent(new InputEvent('input', {
                    bubbles: true,
                    inputType: 'insertText',
                    data: description,
                  }));
                  target.dispatchEvent(new Event('change', { bubbles: true }));
                  return true;
                }
                """,
                description,
            )
        )
    except Exception:
        return False


def _fill_first_matching(page, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.fill(value, timeout=2500)
            return True
        except Exception:
            try:
                locator = page.locator(selector).first
                locator.click(timeout=1500)
                locator.type(value, delay=15, timeout=8000)
                return True
            except Exception:
                continue
    return False


def _best_effort_add_topics(
    page,
    platform: PublisherPlatform,
    topics: list[str],
    job: PublishJob,
) -> None:
    clean_topics = []
    for topic in topics:
        clean = topic.strip().lstrip("#").strip()
        if clean and clean not in clean_topics:
            clean_topics.append(clean)
    if not clean_topics:
        return

    for topic in clean_topics:
        try:
            if not _open_add_topic_entry(page):
                job.logs.append(f"topic_entry_not_found:{topic}")
                continue
            _type_topic_query(page, topic)
            clicked = _click_topic_suggestion(page, topic)
            if not clicked:
                page.keyboard.press("Enter")
                page.wait_for_timeout(800)
            job.logs.append(f"topic_added:{topic}")
        except Exception:
            job.logs.append(f"topic_add_failed:{topic}")


def _add_xiaohongshu_topics(page, topics: list[str], job: PublishJob) -> None:
    for topic in topics:
        try:
            if _open_add_topic_entry(page):
                if _type_topic_query(page, topic):
                    clicked = _click_topic_suggestion(page, topic)
                    if not clicked:
                        page.keyboard.press("Enter")
                        page.wait_for_timeout(800)
                    job.logs.append(f"xhs_topic_added:{topic}")
                    continue
            if _append_xiaohongshu_topic_to_body(page, topic):
                job.logs.append(f"xhs_topic_appended_to_body:{topic}")
            else:
                job.logs.append(f"xhs_topic_entry_not_found:{topic}")
        except Exception:
            job.logs.append(f"xhs_topic_add_failed:{topic}")


def _open_add_topic_entry(page) -> bool:
    candidates = [
        "text=#添加话题",
        "text=添加话题",
        "button:has-text('#添加话题')",
        "button:has-text('添加话题')",
        "[role=button]:has-text('#添加话题')",
        "[role=button]:has-text('添加话题')",
        "span:has-text('#添加话题')",
        "span:has-text('添加话题')",
    ]
    for selector in candidates:
        try:
            page.locator(selector).first.click(timeout=2500)
            page.wait_for_timeout(500)
            return True
        except Exception:
            continue
    return False


def _type_topic_query(page, topic: str) -> bool:
    topic_inputs = [
        "input[placeholder*='话题']",
        "textarea[placeholder*='话题']",
        "input[placeholder*='搜索']",
    ]
    for selector in topic_inputs:
        try:
            locator = page.locator(selector).last
            locator.fill(topic, timeout=1200)
            page.wait_for_timeout(900)
            return True
        except Exception:
            continue
    return False


def _append_xiaohongshu_topic_to_body(page, topic: str) -> bool:
    suffix = f" #{topic}"
    selectors = [
        "textarea[placeholder*='正文']",
        "textarea[placeholder*='描述']",
        "textarea[placeholder*='分享']",
        "[contenteditable=true][data-placeholder*='正文']",
        "[contenteditable=true][data-placeholder*='描述']",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            locator.click(timeout=1500)
            page.keyboard.press("End")
            page.keyboard.type(suffix, delay=15)
            page.wait_for_timeout(300)
            return True
        except Exception:
            continue
    return False


def _click_topic_suggestion(page, topic: str) -> bool:
    candidates = [
        f"text=#{topic}",
        f"text=# {topic}",
        f"text={topic}",
        f"span:has-text('{topic}')",
        f"div:has-text('{topic}')",
    ]
    for selector in candidates:
        try:
            page.locator(selector).last.click(timeout=1200)
            page.wait_for_timeout(400)
            return True
        except Exception:
            continue
    return False


def _wait_for_upload_ready(page, job: PublishJob) -> None:
    busy_texts = ["上传中", "处理中", "转码中", "解析中"]
    deadline_ms = 180000
    elapsed = 0
    while elapsed < deadline_ms:
        if _is_text_visible(page, "上传失败"):
            job.logs.append("upload_failed_visible")
            return
        busy = any(_is_text_visible(page, text) for text in busy_texts)
        if not busy:
            job.logs.append("upload_ready")
            return
        page.wait_for_timeout(2000)
        elapsed += 2000
    job.logs.append("upload_ready_timeout")


def _best_effort_click_action(
    page,
    mode: str,
    platform: PublisherPlatform | None = None,
    job: PublishJob | None = None,
) -> bool:
    if platform == PublisherPlatform.xiaohongshu:
        return _click_xiaohongshu_action(page, mode, job)
    if platform == PublisherPlatform.kuaishou:
        return _click_kuaishou_action(page, mode, job)
    if mode == "draft":
        candidates = [
            "button:has-text('暂存离开')",
            "text=暂存离开",
            "button:has-text('保存草稿')",
            "text=保存草稿",
            "button:has-text('存草稿')",
            "text=存草稿",
            "button:has-text('保存并离开')",
            "text=保存并离开",
            "button:has-text('草稿')",
        ]
    else:
        candidates = [
            "button:has-text('立即发布')",
            "text=立即发布",
            "button:has-text('发布')",
            "text=发布",
            "button:has-text('发表')",
            "text=发表",
        ]
    for selector in candidates:
        try:
            page.locator(selector).last.click(timeout=5000)
            return True
        except Exception:
            continue
    return False


def _click_xiaohongshu_action(page, mode: str, job: PublishJob | None = None) -> bool:
    _apply_platform_page_zoom(page, PublisherPlatform.xiaohongshu)
    _dismiss_xiaohongshu_overlays(page)
    _scroll_xiaohongshu_to_bottom(page)
    labels = (
        ["保存草稿", "存草稿", "暂存", "保存"]
        if mode == "draft"
        else ["发布", "立即发布", "发布笔记"]
    )
    if mode != "draft" and _click_xiaohongshu_red_publish_button(page, job):
        return True
    if _click_xiaohongshu_action_by_dom(page, labels):
        return True
    if _click_xiaohongshu_action_by_coordinates(page, labels):
        return True
    if mode != "draft" and _click_xiaohongshu_publish_fixed_points(page):
        return True
    for label in labels:
        selectors = [
            f"button:has-text('{label}')",
            f"[role=button]:has-text('{label}')",
            f"div[class*='btn']:has-text('{label}')",
            f"div[class*='button']:has-text('{label}')",
        ]
        for selector in selectors:
            try:
                locator = page.locator(selector).filter(has_not_text="发布笔记")
                count = locator.count()
                for index in range(count - 1, -1, -1):
                    item = locator.nth(index)
                    if not item.is_visible(timeout=500):
                        continue
                    box = item.bounding_box(timeout=500)
                    if not box:
                        continue
                    # Avoid the left navigation publish-entry button.
                    if box["x"] < 300:
                        continue
                    text = "".join(item.inner_text(timeout=500).split())
                    if mode != "draft" and _is_xiaohongshu_blocked_publish_text(text):
                        continue
                    if label == "发布" and text != "发布":
                        continue
                    if label != "发布" and text != label and not text.endswith(label):
                        continue
                    item.scroll_into_view_if_needed(timeout=1000)
                    item.click(timeout=3000)
                    return True
            except Exception:
                continue
    return False


def _click_kuaishou_action(page, mode: str, job: PublishJob | None = None) -> bool:
    _dismiss_kuaishou_overlays(page, job)
    _scroll_page_to_bottom(page)
    labels = (
        ["存草稿", "保存草稿", "草稿"]
        if mode == "draft"
        else ["发布", "立即发布", "发布作品"]
    )
    if _click_kuaishou_action_by_dom(page, labels, job):
        return True
    if mode != "draft" and _click_platform_publish_button_by_screenshot(
        page,
        job,
        prefix="ks",
        min_red=155,
        max_green=120,
        max_blue=170,
    ):
        return True
    return False


def _dismiss_kuaishou_overlays(page, job: PublishJob | None = None) -> None:
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(250)
        except Exception:
            pass
    selectors = [
        "[class*='close']",
        "[aria-label*='close' i]",
        "[aria-label*='关闭']",
        "button:has-text('×')",
        "span:has-text('×')",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
            for index in range(count - 1, -1, -1):
                item = locator.nth(index)
                if not item.is_visible(timeout=300):
                    continue
                box = item.bounding_box(timeout=300)
                if not box:
                    continue
                if box["x"] < 180 or box["y"] > 500:
                    continue
                item.click(timeout=800, force=True)
                page.wait_for_timeout(500)
                if job is not None:
                    job.logs.append("ks_overlay_closed")
                return
        except Exception:
            continue
    try:
        closed = bool(
            page.evaluate(
                """
                () => {
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                      style.visibility !== 'hidden' &&
                      rect.width > 8 &&
                      rect.height > 8 &&
                      rect.top >= 0 &&
                      rect.left >= 0;
                  };
                  const hasGuide = Array.from(document.querySelectorAll('body *'))
                    .some((el) => isVisible(el) && /作品信息|下一步|1\\/4|2\\/4|3\\/4|4\\/4/.test(el.innerText || el.textContent || ''));
                  if (!hasGuide) return false;
                  const candidates = Array.from(document.querySelectorAll('button,span,div,i,svg'))
                    .filter(isVisible)
                    .map((el) => {
                      const rect = el.getBoundingClientRect();
                      const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                      const cls = String(el.className || '');
                      const aria = String(el.getAttribute('aria-label') || '');
                      let score = 0;
                      if (/close|关闭/i.test(`${cls} ${aria}`)) score += 1000;
                      if (text === '×' || text === 'x' || text === 'X') score += 1000;
                      if (rect.left > 250 && rect.left < window.innerWidth * 0.65 && rect.top < window.innerHeight * 0.5) score += 300;
                      score -= Math.abs(rect.width - 16);
                      score -= Math.abs(rect.height - 16);
                      return { el, rect, text, cls, aria, score };
                    })
                    .filter((item) => item.score > 800)
                    .sort((a, b) => b.score - a.score);
                  const target = candidates[0]?.el;
                  if (!target) return false;
                  target.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
                  target.dispatchEvent(new MouseEvent('click', { bubbles: true }));
                  if (typeof target.click === 'function') target.click();
                  return true;
                }
                """
            )
        )
        if closed and job is not None:
            job.logs.append("ks_overlay_closed_by_dom")
        if closed:
            page.wait_for_timeout(500)
    except Exception:
        pass


def _click_kuaishou_action_by_dom(
    page,
    labels: list[str],
    job: PublishJob | None = None,
) -> bool:
    try:
        target = page.evaluate(
            """
            (labels) => {
              const clean = (text) => (text || '').replace(/\\s+/g, '').trim();
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  Number(style.opacity || 1) > 0.2 &&
                  rect.width >= 40 &&
                  rect.height >= 24 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  rect.top < window.innerHeight &&
                  rect.left < window.innerWidth;
              };
              const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'))
                .filter(isVisible)
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const text = clean(el.innerText || el.textContent || el.getAttribute('aria-label'));
                  const cls = String(el.className || '');
                  const style = window.getComputedStyle(el);
                  const disabled = el.disabled ||
                    el.getAttribute('aria-disabled') === 'true' ||
                    /disabled/i.test(cls) ||
                    style.pointerEvents === 'none';
                  let score = 0;
                  if (labels.some((label) => text === label || text.endsWith(label))) score += 5000;
                  if (/primary|submit|publish|button|btn/i.test(cls)) score += 1000;
                  if (rect.top > window.innerHeight * 0.45) score += 500;
                  score += rect.top;
                  score += rect.left / 10;
                  return { el, rect, text, cls, disabled, score };
                })
                .filter((item) => {
                  if (item.disabled) return false;
                  if (item.rect.left < 180) return false;
                  if (item.rect.width > 360 || item.rect.height > 120) return false;
                  return labels.some((label) => item.text === label || item.text.endsWith(label));
                })
                .sort((a, b) => b.score - a.score);
              const selected = nodes[0];
              if (!selected) return null;
              selected.el.scrollIntoView({ block: 'center', inline: 'center' });
              const rect = selected.el.getBoundingClientRect();
              const x = rect.left + rect.width / 2;
              const y = rect.top + rect.height / 2;
              return {
                x,
                y,
                text: selected.text,
                cls: selected.cls.slice(0, 100),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };
            }
            """,
            labels,
        )
        if not target:
            if job is not None:
                job.logs.append("ks_publish_candidate:not_found")
            return False
        if job is not None:
            job.logs.append(
                "ks_publish_target:"
                f"text={str(target.get('text') or '')[:24]};"
                f"x={target.get('x'):.1f};y={target.get('y'):.1f};"
                f"size={target.get('width')}x{target.get('height')}"
            )
        page.mouse.click(float(target["x"]), float(target["y"]))
        page.wait_for_timeout(1200)
        return True
    except Exception as exc:
        if job is not None:
            job.logs.append(f"ks_publish_click_exception:{str(exc)[:160]}")
        return False


def _dismiss_xiaohongshu_overlays(page) -> None:
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)
    except Exception:
        pass
    try:
        page.evaluate(
            """
            () => {
              if (document.activeElement && typeof document.activeElement.blur === 'function') {
                document.activeElement.blur();
              }
            }
            """
        )
        page.wait_for_timeout(200)
    except Exception:
        pass


def _is_xiaohongshu_blocked_publish_text(text: str) -> bool:
    blocked = [
        "定时发布",
        "发布时间",
        "发布设置",
        "发布入口",
        "发布记录",
        "发布须知",
        "暂存离开",
        "保存草稿",
    ]
    return any(part in text for part in blocked)


def _click_xiaohongshu_red_publish_button(page, job: PublishJob | None = None) -> bool:
    """Click the real red publish action in the XHS bottom action area."""
    try:
        target = None
        for zoom in ("1", "0.67"):
            _set_xiaohongshu_page_zoom(page, zoom)
            _dismiss_xiaohongshu_overlays(page)
            _scroll_xiaohongshu_to_bottom(page)
            target = page.evaluate(
                """
                (zoom) => {
                  const clean = (text) => (text || '').replace(/\\s+/g, '').trim();
                  const rgb = (color) => {
                    const match = String(color || '').match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                    return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : [0, 0, 0];
                  };
                  const isRedColor = (color) => {
                    const [r, g, b] = rgb(color);
                    return r > 200 && g < 130 && b < 150;
                  };
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                      style.visibility !== 'hidden' &&
                      Number(style.opacity || 1) > 0.2 &&
                      rect.width >= 8 &&
                      rect.height >= 8 &&
                      rect.bottom > 0 &&
                      rect.right > 0 &&
                      rect.top < window.innerHeight &&
                      rect.left < window.innerWidth;
                  };
                  const nearestClickable = (el) =>
                    el.closest('button,[role="button"],a,[class*="btn"],[class*="button"],[class*="submit"]') || el;
                  const redAncestor = (el) => {
                    let current = el;
                    for (let depth = 0; current && depth < 6; depth += 1) {
                      const style = window.getComputedStyle(current);
                      if (isRedColor(style.backgroundColor)) {
                        return { el: current, color: style.backgroundColor };
                      }
                      current = current.parentElement;
                    }
                    return null;
                  };
                  const fireClick = (target) => {
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    const rect = target.getBoundingClientRect();
                    const opts = {
                      bubbles: true,
                      cancelable: true,
                      view: window,
                      clientX: rect.left + rect.width / 2,
                      clientY: rect.top + rect.height / 2,
                    };
                    for (const eventName of [
                      'pointerover', 'pointerenter', 'mouseover', 'mouseenter',
                      'pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click',
                    ]) {
                      const EventClass = eventName.startsWith('pointer') ? PointerEvent : MouseEvent;
                      target.dispatchEvent(new EventClass(eventName, opts));
                    }
                    if (typeof target.click === 'function') target.click();
                  };
                  const all = Array.from(document.querySelectorAll('body *'))
                    .filter(isVisible)
                    .map((el) => {
                      const clickable = nearestClickable(el);
                      const red = redAncestor(el) || redAncestor(clickable);
                      const target = red?.el || clickable || el;
                      const rect = target.getBoundingClientRect();
                      const style = window.getComputedStyle(target);
                      const text = clean(
                        target.innerText ||
                        target.textContent ||
                        el.innerText ||
                        el.textContent ||
                        target.getAttribute('aria-label') ||
                        el.getAttribute('aria-label')
                      );
                      const cls = String(target.className || el.className || '');
                      const tag = target.tagName.toLowerCase();
                      const isRed = Boolean(red) || isRedColor(style.backgroundColor);
                      const hasPublishText = text === '发布' || text === '立即发布' || text === '发布笔记';
                      const blockedText = /定时发布|发布时间|发布设置|发布入口|发布记录|发布须知|暂存离开|保存草稿/.test(text);
                      const disabled = target.disabled ||
                        target.getAttribute('aria-disabled') === 'true' ||
                        /disabled/i.test(cls) ||
                        style.pointerEvents === 'none';
                      const bottomAction = rect.left > 300 &&
                        rect.top > window.innerHeight * 0.45 &&
                        rect.width >= 40 &&
                        rect.width <= 360 &&
                        rect.height >= 24 &&
                        rect.height <= 120;
                      let score = 0;
                      if (bottomAction) score += 5000;
                      if (isRed) score += 10000;
                      if (hasPublishText) score += 12000;
                      if (/primary|submit|publish|red|btn/i.test(cls)) score += 1000;
                      score += rect.top;
                      score += rect.left / 10;
                      return {
                        el,
                        target,
                        rect,
                        text,
                        cls,
                        tag,
                        backgroundColor: red?.color || style.backgroundColor,
                        isRed,
                        hasPublishText,
                        blockedText,
                        disabled,
                        bottomAction,
                        score,
                      };
                    });
                  const candidates = all
                    .filter((item) => {
                      if (item.disabled || item.blockedText || !item.bottomAction) return false;
                      return item.hasPublishText || item.isRed;
                    })
                    .sort((a, b) => b.score - a.score);
                  const debug = all
                    .filter((item) =>
                      item.rect.left > 300 &&
                      item.rect.top > window.innerHeight * 0.35 &&
                      (item.isRed || /发布/.test(item.text))
                    )
                    .sort((a, b) => b.score - a.score)
                    .slice(0, 5)
                    .map((item) => ({
                      text: item.text,
                      tag: item.tag,
                      cls: item.cls.slice(0, 80),
                      x: Math.round(item.rect.left),
                      y: Math.round(item.rect.top),
                      width: Math.round(item.rect.width),
                      height: Math.round(item.rect.height),
                      backgroundColor: item.backgroundColor,
                      isRed: item.isRed,
                      score: Math.round(item.score),
                    }));
                  const selected = candidates[0];
                  if (!selected) {
                    return { clicked: false, zoom, candidates: debug };
                  }
                  fireClick(selected.target);
                  const rect = selected.target.getBoundingClientRect();
                  return {
                    clicked: true,
                    zoom,
                    x: rect.left + rect.width / 2,
                    y: rect.top + rect.height / 2,
                    text: selected.text,
                    tag: selected.tag,
                    cls: selected.cls.slice(0, 120),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height),
                    backgroundColor: selected.backgroundColor,
                    isRed: selected.isRed,
                    viewportWidth: window.innerWidth,
                    viewportHeight: window.innerHeight,
                    candidates: candidates.slice(0, 5).map((item) => ({
                      text: item.text,
                      tag: item.tag,
                      cls: item.cls.slice(0, 80),
                      x: Math.round(item.rect.left),
                      y: Math.round(item.rect.top),
                      width: Math.round(item.rect.width),
                      height: Math.round(item.rect.height),
                      backgroundColor: item.backgroundColor,
                      isRed: item.isRed,
                      score: Math.round(item.score),
                    })),
                  };
                }
                """,
                zoom,
            )
            _append_xiaohongshu_publish_candidate_logs(job, target)
            if target and target.get("clicked"):
                break
            if _click_xiaohongshu_publish_button_by_screenshot(page, job, zoom):
                return True
        if not target or not target.get("clicked"):
            return False
        x = float(target["x"])
        y = float(target["y"])
        page.mouse.move(x, y)
        page.wait_for_timeout(150)
        page.mouse.down()
        page.wait_for_timeout(120)
        page.mouse.up()
        page.wait_for_timeout(350)
        page.evaluate(
            """
            ({ x, y }) => {
              const el = document.elementFromPoint(x, y);
              if (!el) return;
              const target = el.closest('button,[role="button"],a,[class*="btn"],[class*="button"]') || el;
              const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y };
              target.dispatchEvent(new MouseEvent('mousemove', opts));
              target.dispatchEvent(new MouseEvent('mousedown', opts));
              target.dispatchEvent(new MouseEvent('mouseup', opts));
              target.dispatchEvent(new MouseEvent('click', opts));
              if (typeof target.click === 'function') target.click();
            }
            """,
            {"x": x, "y": y},
        )
        page.wait_for_timeout(1500)
        return True
    except Exception as exc:
        if job is not None:
            job.logs.append(f"xhs_publish_click_exception:{str(exc)[:160]}")
        return False


def _set_xiaohongshu_page_zoom(page, zoom: str) -> None:
    try:
        page.evaluate(
            """
            (zoom) => {
              document.documentElement.style.zoom = zoom;
              document.body.style.minWidth = zoom === '1' ? '' : '1600px';
            }
            """,
            zoom,
        )
        page.wait_for_timeout(250)
    except Exception:
        pass


def _click_platform_publish_button_by_screenshot(
    page,
    job: PublishJob | None,
    prefix: str,
    min_red: int,
    max_green: int,
    max_blue: int,
) -> bool:
    """Locate a bottom colored publish button visually and click its center."""
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        if job is not None:
            job.logs.append(f"{prefix}_visual_click_unavailable:{str(exc)[:120]}")
        return False

    try:
        screenshot = page.screenshot(full_page=False)
        image = cv2.imdecode(np.frombuffer(screenshot, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            if job is not None:
                job.logs.append(f"{prefix}_visual_click_no_image")
            return False
        height, width = image.shape[:2]
        blue, green, red = cv2.split(image)
        mask = (
            (red > min_red)
            & (green < max_green)
            & (blue < max_blue)
        ).astype("uint8") * 255
        mask[: int(height * 0.38), :] = 0
        mask[:, : min(180, int(width * 0.13))] = 0
        kernel = np.ones((3, 9), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        candidates: list[dict[str, float]] = []
        for index in range(1, count):
            x, y, box_width, box_height, area = stats[index]
            if area < 120:
                continue
            if box_width < 35 or box_height < 16:
                continue
            if box_width > 420 or box_height > 120:
                continue
            if y < height * 0.42:
                continue
            center_x, center_y = centroids[index]
            score = float(area) + float(y) * 2 + float(center_x) / 4
            candidates.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "width": float(box_width),
                    "height": float(box_height),
                    "area": float(area),
                    "center_x": float(center_x),
                    "center_y": float(center_y),
                    "score": score,
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        if job is not None:
            for index, item in enumerate(candidates[:3]):
                job.logs.append(
                    f"{prefix}_visual_candidate:"
                    f"{index};x={item['x']:.0f};y={item['y']:.0f};"
                    f"size={item['width']:.0f}x{item['height']:.0f};"
                    f"area={item['area']:.0f};center={item['center_x']:.1f},{item['center_y']:.1f}"
                )
        if not candidates:
            if job is not None:
                job.logs.append(f"{prefix}_visual_candidate:not_found;image={width}x{height}")
            return False
        target = candidates[0]
        viewport = page.viewport_size or {"width": width, "height": height}
        click_x = target["center_x"] * viewport["width"] / width
        click_y = target["center_y"] * viewport["height"] / height
        if job is not None:
            job.logs.append(
                f"{prefix}_visual_target:"
                f"x={click_x:.1f};y={click_y:.1f};"
                f"image={width}x{height};viewport={viewport['width']}x{viewport['height']}"
            )
        page.mouse.move(click_x, click_y)
        page.wait_for_timeout(120)
        page.mouse.down()
        page.wait_for_timeout(120)
        page.mouse.up()
        page.wait_for_timeout(500)
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(1500)
        return True
    except Exception as exc:
        if job is not None:
            job.logs.append(f"{prefix}_visual_click_exception:{str(exc)[:160]}")
        return False


def _click_xiaohongshu_publish_button_by_screenshot(
    page,
    job: PublishJob | None,
    zoom: str,
) -> bool:
    """Fallback for XHS: locate the bottom red publish button visually."""
    try:
        import cv2
        import numpy as np
    except Exception as exc:
        if job is not None:
            job.logs.append(f"xhs_visual_click_unavailable:{str(exc)[:120]}")
        return False

    try:
        screenshot = page.screenshot(full_page=False)
        image = cv2.imdecode(np.frombuffer(screenshot, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            if job is not None:
                job.logs.append(f"xhs_visual_click_no_image;zoom={zoom}")
            return False
        height, width = image.shape[:2]
        blue, green, red = cv2.split(image)
        mask = (
            (red > 190)
            & (green < 130)
            & (blue < 170)
        ).astype("uint8") * 255
        mask[: int(height * 0.38), :] = 0
        mask[:, : min(300, int(width * 0.16))] = 0
        kernel = np.ones((3, 9), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        candidates: list[dict[str, float]] = []
        for index in range(1, count):
            x, y, box_width, box_height, area = stats[index]
            if area < 120:
                continue
            if box_width < 35 or box_height < 16:
                continue
            if box_width > 360 or box_height > 100:
                continue
            if y < height * 0.42:
                continue
            center_x, center_y = centroids[index]
            score = float(area) + float(y) * 2 + float(center_x) / 4
            candidates.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "width": float(box_width),
                    "height": float(box_height),
                    "area": float(area),
                    "center_x": float(center_x),
                    "center_y": float(center_y),
                    "score": score,
                }
            )
        candidates.sort(key=lambda item: item["score"], reverse=True)
        if job is not None:
            for index, item in enumerate(candidates[:3]):
                job.logs.append(
                    "xhs_visual_candidate:"
                    f"{index};zoom={zoom};x={item['x']:.0f};y={item['y']:.0f};"
                    f"size={item['width']:.0f}x{item['height']:.0f};"
                    f"area={item['area']:.0f};center={item['center_x']:.1f},{item['center_y']:.1f}"
                )
        if not candidates:
            if job is not None:
                job.logs.append(f"xhs_visual_candidate:not_found;zoom={zoom};image={width}x{height}")
            return False

        target = candidates[0]
        viewport = page.viewport_size or {"width": width, "height": height}
        click_x = target["center_x"] * viewport["width"] / width
        click_y = target["center_y"] * viewport["height"] / height
        if job is not None:
            job.logs.append(
                "xhs_visual_target:"
                f"zoom={zoom};x={click_x:.1f};y={click_y:.1f};"
                f"image={width}x{height};viewport={viewport['width']}x{viewport['height']}"
            )
        page.mouse.move(click_x, click_y)
        page.wait_for_timeout(120)
        page.mouse.down()
        page.wait_for_timeout(120)
        page.mouse.up()
        page.wait_for_timeout(500)
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(1500)
        return True
    except Exception as exc:
        if job is not None:
            job.logs.append(f"xhs_visual_click_exception:{str(exc)[:160]}")
        return False


def _append_xiaohongshu_publish_candidate_logs(
    job: PublishJob | None,
    target: dict | bool | None,
) -> None:
    if job is None:
        return
    if not isinstance(target, dict):
        job.logs.append("xhs_publish_candidate:none")
        return
    if not target.get("clicked"):
        job.logs.append(f"xhs_publish_candidate:not_found;zoom={target.get('zoom')}")
    else:
        text = str(target.get("text") or "")[:24]
        cls = str(target.get("cls") or "")[:60].replace(" ", ".")
        job.logs.append(
            "xhs_publish_target:"
            f"text={text};zoom={target.get('zoom')};"
            f"x={target.get('x'):.1f};y={target.get('y'):.1f};"
            f"size={target.get('width')}x{target.get('height')};"
            f"bg={target.get('backgroundColor')};red={target.get('isRed')};class={cls}"
        )
    candidates = target.get("candidates")
    if isinstance(candidates, list):
        for index, item in enumerate(candidates[:3]):
            text = str(item.get("text") or "")[:20]
            cls = str(item.get("cls") or "")[:40].replace(" ", ".")
            job.logs.append(
                "xhs_publish_candidate:"
                f"{index};text={text};x={item.get('x')};y={item.get('y')};"
                f"size={item.get('width')}x{item.get('height')};"
                f"bg={item.get('backgroundColor')};red={item.get('isRed')};"
                f"score={item.get('score')};class={cls}"
            )


def _click_xiaohongshu_publish_fixed_points(page) -> bool:
    """Deprecated coordinate fallback.

    XHS layout changes with viewport and browser zoom. Fixed viewport-ratio
    clicks have already proven too risky because they can hit blank space or
    nearby controls instead of the real red publish action.
    """
    return False


def _scroll_xiaohongshu_to_bottom(page) -> None:
    _scroll_page_to_bottom(page)


def _scroll_page_to_bottom(page) -> None:
    for _ in range(8):
        try:
            page.mouse.wheel(0, 1800)
        except Exception:
            pass
        try:
            page.keyboard.press("PageDown")
        except Exception:
            pass
        try:
            page.evaluate(
                """
                () => {
                  const scrollables = [document.scrollingElement, document.documentElement, document.body]
                    .concat(Array.from(document.querySelectorAll('*')).filter((el) => {
                      const style = window.getComputedStyle(el);
                      return /(auto|scroll)/.test(style.overflowY) &&
                        el.scrollHeight > el.clientHeight + 20;
                    }));
                  for (const el of scrollables) {
                    if (!el) continue;
                    try { el.scrollTop = el.scrollHeight; } catch (_) {}
                  }
                  window.scrollTo(0, document.body.scrollHeight);
                }
                """
            )
        except Exception:
            pass
        try:
            page.wait_for_timeout(350)
        except Exception:
            pass


def _click_xiaohongshu_action_by_coordinates(page, labels: list[str]) -> bool:
    try:
        box = page.evaluate(
            """
            (labels) => {
              const directMode = labels.includes('发布');
              const clean = (text) => (text || '').replace(/\\s+/g, '').trim();
              const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                  style.visibility !== 'hidden' &&
                  rect.width > 20 &&
                  rect.height > 20 &&
                  rect.bottom > 0 &&
                  rect.right > 0 &&
                  rect.top < window.innerHeight &&
                  rect.left < window.innerWidth;
              };
              const nodes = Array.from(document.querySelectorAll('button,[role="button"],a,div,span'))
                .filter(isVisible)
                .map((el) => {
                  const rect = el.getBoundingClientRect();
                  const text = clean(el.innerText || el.textContent);
                  const cls = String(el.className || '');
                  const aria = clean(el.getAttribute('aria-label') || '');
                  return { el, rect, text, cls, aria };
                })
                .filter((item) => {
                  const text = item.text || item.aria;
                  if (directMode && /定时发布|发布时间|发布设置|发布入口|发布记录|发布须知|暂存离开|保存草稿/.test(text)) return false;
                  if (!labels.some((label) => text === label || (label !== '发布' && text.endsWith(label)))) return false;
                  if (item.text.includes('发布笔记') && item.rect.left < 320) return false;
                  if (item.rect.left < 320) return false;
                  if (item.rect.width > 260 || item.rect.height > 80) return false;
                  return true;
                })
                .sort((a, b) => {
                  const primaryA = /btn|button|primary|submit/i.test(a.cls) ? 1 : 0;
                  const primaryB = /btn|button|primary|submit/i.test(b.cls) ? 1 : 0;
                  return primaryB - primaryA || b.rect.top - a.rect.top || b.rect.left - a.rect.left;
                });
              const target = nodes[0];
              if (!target) return null;
              return {
                x: target.rect.left + target.rect.width / 2,
                y: target.rect.top + target.rect.height / 2,
                text: target.text || target.aria
              };
            }
            """,
            labels,
        )
        if not box:
            return False
        page.mouse.click(box["x"], box["y"])
        page.wait_for_timeout(1000)
        return True
    except Exception:
        return False


def _click_xiaohongshu_action_by_dom(page, labels: list[str]) -> bool:
    try:
        return bool(
            page.evaluate(
                """
                (labels) => {
                  const directMode = labels.includes('发布');
                  const scrollables = [document.scrollingElement, document.documentElement, document.body]
                    .concat(Array.from(document.querySelectorAll('*')).filter((el) =>
                      el.scrollHeight > el.clientHeight + 20
                    ));
                  for (const el of scrollables) {
                    if (!el) continue;
                    try { el.scrollTop = el.scrollHeight; } catch (_) {}
                  }
                  const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none' &&
                      style.visibility !== 'hidden' &&
                      rect.width > 20 &&
                      rect.height > 20;
                  };
                  const nodes = Array.from(document.querySelectorAll('button,[role="button"],div,span'))
                    .filter(isVisible)
                    .map((el) => {
                      const rect = el.getBoundingClientRect();
                      const text = (el.innerText || el.textContent || '').replace(/\\s+/g, '').trim();
                      const cls = String(el.className || '');
                      return { el, rect, text, cls };
                    })
                    .filter((item) =>
                      item.rect.x > 300 &&
                      !(directMode && /定时发布|发布时间|发布设置|发布入口|发布记录|发布须知|暂存离开|保存草稿/.test(item.text)) &&
                      labels.some((label) => item.text === label || (label !== '发布' && item.text.endsWith(label))) &&
                      !(item.text.includes('发布笔记') && item.rect.x < 320) &&
                      item.rect.width <= 280 &&
                      item.rect.height <= 90
                    )
                    .sort((a, b) => {
                      const primaryA = /btn|button|primary|submit/i.test(a.cls) ? 1 : 0;
                      const primaryB = /btn|button|primary|submit/i.test(b.cls) ? 1 : 0;
                      return primaryB - primaryA || b.rect.y - a.rect.y || b.rect.x - a.rect.x;
                    });
                  let target = nodes[0]?.el;
                  if (!target) return false;
                  target = target.closest('button,[role="button"]') || target;
                  target.scrollIntoView({ block: 'center', inline: 'center' });
                  const rect = target.getBoundingClientRect();
                  const opts = {
                    bubbles: true,
                    cancelable: true,
                    view: window,
                    clientX: rect.left + rect.width / 2,
                    clientY: rect.top + rect.height / 2,
                  };
                  target.dispatchEvent(new MouseEvent('mouseover', opts));
                  target.dispatchEvent(new MouseEvent('mouseenter', opts));
                  target.dispatchEvent(new MouseEvent('mousemove', opts));
                  target.dispatchEvent(new MouseEvent('mousedown', opts));
                  target.dispatchEvent(new MouseEvent('mouseup', opts));
                  target.dispatchEvent(new MouseEvent('click', opts));
                  if (typeof target.click === 'function') target.click();
                  return true;
                }
                """,
                labels,
            )
        )
    except Exception:
        return False


def _best_effort_click_confirm(page) -> None:
    candidates = [
        "button:has-text('确认')",
        "button:has-text('确定')",
        "button:has-text('继续发布')",
        "button:has-text('我知道了')",
    ]
    for selector in candidates:
        try:
            page.locator(selector).last.click(timeout=2500)
            page.wait_for_timeout(1000)
            return
        except Exception:
            continue


def _needs_user_verification(page) -> bool:
    texts = [
        "短信验证",
        "验证码",
        "发送验证码",
        "输入验证码",
        "手机验证",
        "安全验证",
        "身份验证",
        "风险验证",
        "请完成验证",
    ]
    return any(_is_text_visible(page, text) for text in texts)


def _action_success_texts(mode: str) -> list[str]:
    if mode == "draft":
        return ["保存成功", "草稿保存成功", "已保存草稿", "存入草稿", "暂存成功", "已暂存", "草稿箱"]
    return ["发布成功", "发布完成", "提交成功", "作品提交成功", "审核中", "正在审核"]


def _action_success_visible(
    page,
    mode: str,
    platform: PublisherPlatform | None = None,
) -> bool:
    if any(_is_text_visible(page, text) for text in _action_success_texts(mode)):
        return True
    if platform == PublisherPlatform.xiaohongshu and mode == "direct":
        return _xiaohongshu_returned_to_upload_page(page)
    if platform == PublisherPlatform.shipinhao and mode == "direct":
        return _shipinhao_publish_success_visible(page)
    return False


def _xiaohongshu_returned_to_upload_page(page) -> bool:
    try:
        url = page.url
    except Exception:
        url = ""
    if "creator.xiaohongshu.com" not in url:
        return False
    upload_markers = [
        "拖拽视频到此或点击上传",
        "上传视频",
        "视频大小",
        "视频格式",
        "视频分辨率",
    ]
    visible_count = sum(1 for text in upload_markers if _is_text_visible(page, text))
    if visible_count < 3:
        return False
    # The filled publish form contains these controls; if they are still
    # visible, the page has not returned to the upload-start state yet.
    form_markers = ["设置封面", "添加标题", "添加章节", "定时发布"]
    if any(_is_text_visible(page, text) for text in form_markers):
        return False
    return True


def _shipinhao_publish_success_visible(page) -> bool:
    success_texts = ["发布成功", "发表成功", "审核中", "已发表", "发表动态成功"]
    if any(_is_text_visible(page, text) for text in success_texts):
        return True
    # Channels can land on the post-publish edit page instead of showing a
    # toast long enough for Playwright to observe it.
    if _is_text_visible(page, "视频管理") and _is_text_visible(page, "修改描述和封面"):
        return True
    return False


def _wait_for_action_result(page, mode: str) -> bool:
    deadline_ms = 45000
    elapsed = 0
    while elapsed < deadline_ms:
        if _action_success_visible(page, mode):
            return True
        page.wait_for_timeout(1500)
        elapsed += 1500
    return False


def _wait_for_manual_action_result(
    page,
    context,
    account: PublisherAccount,
    job: PublishJob,
    mode: str,
) -> bool:
    deadline = time.monotonic() + _manual_action_timeout_seconds()
    last_saved = 0.0
    while time.monotonic() < deadline:
        if page.is_closed():
            job.logs.append("manual_verification_window_closed")
            _save_browser_state(context, account)
            return False
        if _action_success_visible(page, mode, account.platform):
            job.logs.append("manual_verification_completed")
            _save_browser_state(context, account)
            return True
        now = time.monotonic()
        if now - last_saved > 15:
            _save_browser_state(context, account)
            last_saved = now
        page.wait_for_timeout(3000)
    job.logs.append("manual_verification_timeout")
    _save_browser_state(context, account)
    return False


def _wait_for_upload_control(
    page,
    context,
    account: PublisherAccount,
    job: PublishJob,
    platform: PublisherPlatform,
    publish_url: str,
) -> bool:
    deadline = time.monotonic() + _manual_action_timeout_seconds()
    navigated_after_login = False
    while time.monotonic() < deadline:
        if page.is_closed():
            job.logs.append("upload_control_wait_window_closed")
            _save_browser_state(context, account)
            return False
        try:
            page.locator("input[type=file]").first.wait_for(timeout=3000)
            _save_browser_state(context, account)
            job.logs.append("upload_control_available_after_user_action")
            return True
        except Exception:
            pass
        if not navigated_after_login and _looks_logged_in(page, platform):
            try:
                page.goto(publish_url, wait_until="domcontentloaded", timeout=60000)
                _apply_platform_page_zoom(page, platform)
                navigated_after_login = True
                job.logs.append("renavigate_publish_after_login")
            except Exception:
                pass
        _save_browser_state(context, account)
        page.wait_for_timeout(3000)
    job.logs.append("upload_control_wait_timeout")
    _save_browser_state(context, account)
    return False


def _manual_action_timeout_seconds() -> int:
    raw = os.getenv("PUBLISHER_MANUAL_ACTION_TIMEOUT_SECONDS", "1800").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1800
    return max(60, min(value, 7200))


def _is_text_visible(page, text: str) -> bool:
    try:
        return page.locator(f"text={text}").first.is_visible(timeout=500)
    except Exception:
        return False


def _capture_job_screenshot(page, job: PublishJob) -> None:
    path = publisher_screenshot_path(job.job_id)
    try:
        page.screenshot(path=str(path), full_page=True)
        job.screenshot_path = str(path)
    except Exception:
        pass
