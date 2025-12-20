# 文件名: notifier.py
import requests
import json
import smtplib
from email.mime.text import MIMEText
from email.header import Header

# ================= 配置区 =================
# 1. 钉钉机器人 (保持不变)
DING_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"

# 2. 邮件发送配置 (以QQ邮箱为例，其他邮箱类似)
SMTP_SERVER = "smtp.qq.com"      # SMTP服务器 (网易: smtp.163.com)
SMTP_PORT = 465                  # SSL端口
SENDER_EMAIL = "your_email@qq.com" # 发件人邮箱 (你的邮箱)
SENDER_PASS = "your_auth_code"     # 邮箱授权码 (注意：不是密码！是SMTP授权码)

# 3. 短信发送配置 (需要阿里云/腾讯云/Twilio等服务商支持)
# 这里仅提供标准模版，实际使用需申请 API
SMS_API_URL = "https://sms-api.example.com/send"
SMS_API_KEY = "your_sms_api_key"

def send_markdown(title, content):
    """发送钉钉 Markdown"""
    if "YOUR_TOKEN" in DING_WEBHOOK: return
    headers = {"Content-Type": "application/json"}
    data = {"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n\n{content}"}}
    try:
        requests.post(DING_WEBHOOK, json=data, headers=headers)
        print("✅ [钉钉] 消息已推送")
    except: pass

def send_email(to_addr, title, content):
    """发送邮件 (HTML格式)"""
    if not to_addr or "@" not in to_addr:
        print("⚠️ 未提供有效邮箱，跳过邮件推送")
        return

    if "your_auth_code" in SENDER_PASS:
        print("⚠️ 请先在 notifier.py 中配置邮箱授权码！")
        return

    # 将 Markdown 简单转换为 HTML (为了邮件好看点)
    html_content = content.replace("\n", "<br>").replace("**", "<b>").replace("`", "<span style='color:red'>")
    
    message = MIMEText(html_content, 'html', 'utf-8')
    message['From'] = Header(f"五维超脑 <{SENDER_EMAIL}>", 'utf-8')
    message['To'] = Header(to_addr, 'utf-8')
    message['Subject'] = Header(title, 'utf-8')

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(SENDER_EMAIL, SENDER_PASS)
        server.sendmail(SENDER_EMAIL, [to_addr], message.as_string())
        server.quit()
        print(f"✅ [邮件] 已发送至 {to_addr}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

def send_sms(phone_number, content):
    """发送短信 (需要对接服务商)"""
    if not phone_number or len(phone_number) < 11:
        return
    
    print(f"📡 [模拟短信] 正在向 {phone_number} 发送: 发现高分机会，请查看邮件...")
    # 实际代码示例 (以 HTTP 请求为例):
    # requests.post(SMS_API_URL, data={'key': SMS_API_KEY, 'phone': phone_number, 'msg': '发现投资机会...'})

def notify_daily_report(df_picks, target_email=None, target_phone=None):
    """
    综合推送入口
    """
    if df_picks.empty: return

    # 1. 生成内容
    title = f"🚀 五维超脑·机会雷达 ({len(df_picks)}只)"
    
    # 纯文本/Markdown 内容
    msg_md = f"**📅 扫描时间:** {df_picks.iloc[0].get('date', 'Today')}\n\n"
    for i, row in df_picks.head(5).iterrows():
        msg_md += f"---\n"
        msg_md += f"**{row['名称']} ({row['代码']})** `评分:{row['AI综合分']}`\n"
        msg_md += f"💰 建议: **{row.get('建议持仓', 0)}元**\n"
        msg_md += f"💡 逻辑: {row['总评逻辑'][:30]}...\n"
    msg_md += "\n[详情请查看交易终端]"

    # 2. 执行推送
    # (A) 推送钉钉 (群消息)
    send_markdown(title, msg_md)
    
    # (B) 推送邮件 (个人消息)
    if target_email:
        send_email(target_email, title, msg_md)
        
    # (C) 推送短信 (提醒去看邮件)
    if target_phone:
        send_sms(target_phone, "五维超脑发现高确定性机会，请查看邮件详情。")