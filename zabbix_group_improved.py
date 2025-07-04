#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix 主机组分析工具 - 改进版
功能：
1. 检查主机组下主机的非模板触发器
2. 检查主机宏覆盖情况
3. 检查模板继承中的禁用触发器问题
4. 生成详细的 CSV 分析报告
"""

import requests
import csv
import time
import os
import sys
import json
import logging
from typing import List, Dict, Optional, Tuple
from urllib.parse import urljoin
import re
from pathlib import Path

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('zabbix_analysis.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ZabbixConfig:
    """Zabbix 配置管理类"""
    
    def __init__(self):
        # 直接硬编码配置，避免配置文件复杂性
        self.url = "http://localhost/api_jsonrpc.php"
        self.user = "Admin"
        self.password = "zabbix"
        self.output_dir = "./output"
        self.timeout = 30
        
        self._validate_config()
    
    def _validate_config(self):
        """验证配置"""
        if not self.url:
            raise ValueError("请配置正确的 ZABBIX_URL")
        
        if not self.user or not self.password:
            raise ValueError("请配置 Zabbix 用户名和密码")
        
        # 确保输出目录存在
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

class ZabbixAPI:
    """Zabbix API 客户端"""
    
    def __init__(self, config: ZabbixConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json-rpc"})
        self.auth_token: Optional[str] = None
        self.request_id = 1
    
    def __enter__(self):
        """上下文管理器入口"""
        self.login()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器退出"""
        self.logout()
    
    def _call_api(self, method: str, params: Dict, auth_required: bool = True) -> Dict:
        """调用 Zabbix API"""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self.request_id,
        }
        
        # Zabbix 7.2+ 使用 Authorization Bearer 头部认证，不再使用 auth 参数
        headers = {"Content-Type": "application/json-rpc"}
        if auth_required and self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        self.request_id += 1
        
        try:
            response = self.session.post(
                self.config.url, 
                json=payload, 
                headers=headers,
                timeout=self.config.timeout
            )
            response.raise_for_status()
            
            result = response.json()
            
            if "error" in result:
                error_msg = result["error"].get("data", result["error"].get("message", "未知错误"))
                raise Exception(f"Zabbix API 错误: {error_msg}")
            
            return result.get("result")
            
        except requests.exceptions.Timeout:
            raise Exception(f"API 请求超时 (>{self.config.timeout}s)")
        except requests.exceptions.ConnectionError:
            raise Exception(f"无法连接到 Zabbix 服务器: {self.config.url}")
        except requests.exceptions.HTTPError as e:
            raise Exception(f"HTTP 错误: {e}")
        except json.JSONDecodeError:
            raise Exception("API 响应不是有效的 JSON 格式")
    
    def login(self):
        """登录 Zabbix"""
        logger.info("正在登录 Zabbix...")
        try:
            # 对于 user.login，仍然使用旧的方式（不需要认证头部）
            self.auth_token = self._call_api(
                "user.login",
                {"username": self.config.user, "password": self.config.password},
                auth_required=False
            )
            logger.info("登录成功")
        except Exception as e:
            logger.error(f"登录失败: {e}")
            raise
    
    def logout(self):
        """注销 Zabbix"""
        if self.auth_token:
            try:
                self._call_api("user.logout", {})
                logger.info("已注销")
            except Exception as e:
                logger.warning(f"注销失败: {e}")
            finally:
                self.auth_token = None
    
    def get_hostgroups(self, group_names: List[str]) -> List[Dict]:
        """获取主机组信息"""
        return self._call_api("hostgroup.get", {
            "filter": {"name": group_names},
            "output": ["groupid", "name"]
        })
    
    def get_hosts_by_group(self, groupid: str) -> List[Dict]:
        """获取主机组下的主机"""
        return self._call_api("host.get", {
            "output": ["hostid", "name"],
            "groupids": groupid,
            "selectParentTemplates": ["templateid", "name"]
        })
    
    def get_host_triggers(self, hostid: str) -> List[Dict]:
        """获取主机触发器（仅非模板触发器）"""
        return self._call_api("trigger.get", {
            "hostids": hostid,
            "output": ["triggerid", "description", "flags", "status", "expression", "templateid"],
            "selectItems": ["itemid", "name", "key_"],
            "inherited": False,  # 明确指定不要继承的触发器
            "expandData": True
        })
    
    def get_trigger_items(self, triggerid: str) -> List[Dict]:
        """获取触发器关联的监控项"""
        return self._call_api("item.get", {
            "triggerids": triggerid,
            "output": ["itemid", "name", "key_"]
        })
    
    def get_host_macros(self, hostid: str) -> List[Dict]:
        """获取主机宏"""
        return self._call_api("usermacro.get", {
            "hostids": hostid,
            "output": ["macro", "value"]
        })
    
    def get_template_macros(self, template_ids: List[str]) -> List[Dict]:
        """获取模板宏"""
        if not template_ids:
            return []
        return self._call_api("usermacro.get", {
            "hostids": template_ids,
            "output": ["macro", "value"]
        })
    
    def get_templates_with_inheritance_issues(self) -> List[Tuple[str, str, str]]:
        """检查模板继承问题"""
        logger.info("检查模板继承问题...")
        
        # 获取所有启用的模板
        templates = self._call_api("template.get", {
            "output": ["templateid", "name"],
            "filter": {"status": 0},
            "selectParentTemplates": ["templateid", "name"]
        })
        
        issues = []
        
        for template in templates:
            template_id = template["templateid"]
            template_name = template["name"]
            parent_templates = template.get("parentTemplates", [])
            
            if not parent_templates:
                continue
            
            # 获取模板的触发器
            triggers = self._call_api("trigger.get", {
                "templateids": template_id,
                "output": ["triggerid", "description", "status", "flags"],
                "expandData": True
            })
            
            # 查找被禁用的继承触发器
            disabled_inherited = [
                t for t in triggers 
                if int(t.get("flags", 0)) == 4 and int(t.get("status", 0)) == 1
            ]
            
            if not disabled_inherited:
                continue
            
            # 获取父模板的触发器信息
            parent_ids = [p["templateid"] for p in parent_templates]
            parent_triggers = self._call_api("trigger.get", {
                "templateids": parent_ids,
                "output": ["triggerid", "description", "status"],
                "expandData": True,
                "selectHosts": ["name"]
            })
            
            # 建立描述到父模板的映射
            desc_to_parent = {}
            for pt in parent_triggers:
                desc = pt["description"]
                parent_name = pt["hosts"][0]["name"] if pt["hosts"] else "未知模板"
                desc_to_parent[desc] = parent_name
            
            # 记录问题
            for trigger in disabled_inherited:
                desc = trigger["description"]
                from_template = desc_to_parent.get(desc, "未知模板")
                issues.append((template_name, desc, from_template))
        
        return issues

class ZabbixAnalyzer:
    """Zabbix 分析器"""
    
    def __init__(self, config: ZabbixConfig):
        self.config = config
    
    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名中的特殊字符"""
        # 移除或替换不安全的字符
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'\s+', '_', filename)
        return filename[:100]  # 限制文件名长度
    
    def _load_group_names(self) -> List[str]:
        """加载主机组名称"""
        if len(sys.argv) > 1:
            return sys.argv[1:]
        
        groups_file = "groups.txt"
        if os.path.exists(groups_file):
            try:
                with open(groups_file, "r", encoding="utf-8") as f:
                    groups = [line.strip() for line in f if line.strip()]
                if groups:
                    return groups
            except Exception as e:
                logger.error(f"读取 {groups_file} 失败: {e}")
        
        logger.error("请提供主机组名参数或创建 groups.txt 文件")
        sys.exit(1)
    
    def analyze_hostgroup(self, api: ZabbixAPI, group_name: str, timestamp: str):
        """分析单个主机组"""
        logger.info(f"开始分析主机组: {group_name}")
        
        # 获取主机组
        groups = api.get_hostgroups([group_name])
        if not groups:
            logger.warning(f"主机组不存在: {group_name}")
            return
        
        group_id = groups[0]["groupid"]
        
        # 获取主机
        hosts = api.get_hosts_by_group(group_id)
        if not hosts:
            logger.warning(f"主机组 {group_name} 下无主机")
            return
        
        # 生成报告文件
        safe_name = self._sanitize_filename(group_name)
        filename = os.path.join(
            self.config.output_dir, 
            f"{safe_name}_{timestamp}.csv"
        )
        
        with open(filename, "w", newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["主机名", "问题类型", "触发器描述", "监控项名称", "监控项键值", "详细信息"])
            
            for host in hosts:
                self._analyze_host(api, host, writer)
        
        logger.info(f"主机组 {group_name} 分析完成，报告: {filename}")
    
    def _analyze_host(self, api: ZabbixAPI, host: Dict, writer):
        """分析单个主机"""
        host_id = host["hostid"]
        host_name = host["name"]
        
        try:
            # 检查非模板触发器
            triggers = api.get_host_triggers(host_id)
            for trigger in triggers:
                # 三重检查确保是非继承触发器：
                # 1. inherited=False 已在 API 调用中设置
                # 2. templateid 为空或为 "0"
                # 3. flags 为 0（普通触发器，非发现触发器）
                template_id = trigger.get("templateid", "")
                if (not template_id or template_id == "0") and int(trigger.get("flags", 0)) == 0:
                    # 获取触发器关联的监控项
                    items = trigger.get("items", [])
                    if items:
                        for item in items:
                            writer.writerow([
                                host_name, 
                                "非模板触发器", 
                                trigger["description"],
                                item.get("name", "未知监控项"),
                                item.get("key_", "未知键值"),
                                f"触发器ID: {trigger['triggerid']}, 监控项ID: {item.get('itemid', '未知')}, 表达式: {trigger.get('expression', '未知')}"
                            ])
                    else:
                        # 如果没有关联监控项信息，尝试单独获取
                        try:
                            trigger_items = api.get_trigger_items(trigger["triggerid"])
                            if trigger_items:
                                for item in trigger_items:
                                    writer.writerow([
                                        host_name, 
                                        "非模板触发器", 
                                        trigger["description"],
                                        item.get("name", "未知监控项"),
                                        item.get("key_", "未知键值"),
                                        f"触发器ID: {trigger['triggerid']}, 监控项ID: {item.get('itemid', '未知')}, 表达式: {trigger.get('expression', '未知')}"
                                    ])
                            else:
                                writer.writerow([
                                    host_name, 
                                    "非模板触发器", 
                                    trigger["description"],
                                    "无关联监控项",
                                    "无关联监控项",
                                    f"触发器ID: {trigger['triggerid']}, 表达式: {trigger.get('expression', '未知')}"
                                ])
                        except Exception as e:
                            writer.writerow([
                                host_name, 
                                "非模板触发器", 
                                trigger["description"],
                                "获取监控项失败",
                                "获取监控项失败",
                                f"触发器ID: {trigger['triggerid']}, 错误: {str(e)}"
                            ])
            
            # 检查宏覆盖
            host_macros = api.get_host_macros(host_id)
            
            templates = host.get("parentTemplates", [])
            template_ids = [tpl["templateid"] for tpl in templates]
            
            if template_ids:
                template_macros = api.get_template_macros(template_ids)
                template_macro_map = {m["macro"]: m["value"] for m in template_macros}
                
                for macro in host_macros:
                    macro_name = macro["macro"]
                    host_value = macro["value"]
                    
                    if macro_name in template_macro_map:
                        template_value = template_macro_map[macro_name]
                        if host_value != template_value:
                            writer.writerow([
                                host_name,
                                "覆盖宏",
                                "宏值覆盖",
                                "N/A",
                                "N/A",
                                f"{macro_name} 主机值={host_value} 模板值={template_value}"
                            ])
        
        except Exception as e:
            logger.error(f"分析主机 {host_name} 时出错: {e}")
            writer.writerow([host_name, "分析错误", "系统错误", "N/A", "N/A", str(e)])
    
    def generate_inheritance_report(self, api: ZabbixAPI, timestamp: str):
        """生成模板继承问题报告"""
        logger.info("生成模板继承问题报告...")
        
        try:
            issues = api.get_templates_with_inheritance_issues()
            
            if issues:
                filename = os.path.join(
                    self.config.output_dir,
                    f"模板继承禁用触发器_{timestamp}.csv"
                )
                
                with open(filename, "w", newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["模板名称", "继承触发器描述", "继承来源模板"])
                    for issue in issues:
                        writer.writerow(issue)
                
                logger.info(f"模板继承问题报告完成，共 {len(issues)} 项，文件: {filename}")
            else:
                logger.info("未发现模板继承问题")
        
        except Exception as e:
            logger.error(f"生成模板继承报告时出错: {e}")
    
    def run(self):
        """运行分析"""
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        group_names = self._load_group_names()
        
        logger.info(f"开始分析 {len(group_names)} 个主机组")
        
        try:
            with ZabbixAPI(self.config) as api:
                # 分析每个主机组
                for group_name in group_names:
                    try:
                        self.analyze_hostgroup(api, group_name, timestamp)
                    except Exception as e:
                        logger.error(f"分析主机组 {group_name} 失败: {e}")
                
                # 生成模板继承问题报告
                self.generate_inheritance_report(api, timestamp)
        
        except Exception as e:
            logger.error(f"分析过程中发生错误: {e}")
            sys.exit(1)
        
        logger.info("分析完成")

def create_sample_config():
    """创建示例配置文件"""
    config = {
        "zabbix_url": "http://your-zabbix-server/zabbix/api_jsonrpc.php",
        "zabbix_user": "Admin",
        "zabbix_pass": "your-password",
        "output_dir": "./output",
        "timeout": "30"
    }
    
    with open("zabbix_config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    print("已创建示例配置文件 zabbix_config.json，请修改其中的配置")

def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1] == "--create-config":
        create_sample_config()
        return
    
    try:
        config = ZabbixConfig()
        analyzer = ZabbixAnalyzer(config)
        analyzer.run()
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()