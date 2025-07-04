#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix 检测工具
功能：
1. 检测模板监控项中的非模板触发器
2. 检测非模板的监控项
3. 检测被禁用的触发器与监控项
4. 支持按主机或主机群组进行检测
5. 生成详细的检测报告
"""

import requests
import json
import logging
import sys
import csv
from typing import List, Dict, Optional
from pathlib import Path
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('zabbix_detector.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class ZabbixConfig:
    """Zabbix 配置管理类"""
    
    def __init__(self):
        # 硬编码配置
        self.url = "http://localhost/api_jsonrpc.php"
        self.user = "Admin"
        self.password = "zabbix"
        self.timeout = 30

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
        
        # Zabbix 7.2+ 使用 Authorization Bearer 头部认证
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
    
    def get_hostgroup_by_name(self, group_name: str) -> Optional[Dict]:
        """根据名称获取主机组"""
        groups = self._call_api("hostgroup.get", {
            "filter": {"name": group_name},
            "output": ["groupid", "name"]
        })
        return groups[0] if groups else None
    
    def get_host_by_name(self, host_name: str) -> Optional[Dict]:
        """根据名称获取主机"""
        hosts = self._call_api("host.get", {
            "output": ["hostid", "name"],
            "filter": {"name": host_name},
            "selectParentTemplates": ["templateid", "name"]
        })
        return hosts[0] if hosts else None
    
    def get_hosts_in_group(self, group_id: str) -> List[Dict]:
        """获取主机组中的所有主机"""
        return self._call_api("host.get", {
            "output": ["hostid", "name"],
            "groupids": group_id,
            "selectParentTemplates": ["templateid", "name"]
        })
    
    def get_host_items(self, host_id: str) -> List[Dict]:
        """获取主机的所有监控项"""
        return self._call_api("item.get", {
            "output": ["itemid", "name", "key_", "status", "templateid", "type", "delay"],
            "hostids": host_id,
            "selectTriggers": ["triggerid", "description", "status", "priority", "templateid"]
        })
    
    def get_host_triggers(self, host_id: str) -> List[Dict]:
        """获取主机的所有触发器"""
        return self._call_api("trigger.get", {
            "output": ["triggerid", "description", "expression", "priority", "status", "templateid"],
            "hostids": host_id,
            "selectItems": ["itemid", "name", "key_", "templateid"]
        })

class ZabbixDetector:
    """Zabbix 检测器"""
    
    def __init__(self, api: ZabbixAPI):
        self.api = api
    
    def detect_by_host(self, host_name: str) -> Dict:
        """按主机检测"""
        logger.info(f"开始检测主机: {host_name}")
        
        host = self.api.get_host_by_name(host_name)
        if not host:
            logger.error(f"主机 '{host_name}' 不存在")
            return {}
        
        return self._detect_host_issues(host)
    
    def detect_by_hostgroup(self, group_name: str) -> Dict:
        """按主机组检测"""
        logger.info(f"开始检测主机组: {group_name}")
        
        group = self.api.get_hostgroup_by_name(group_name)
        if not group:
            logger.error(f"主机组 '{group_name}' 不存在")
            return {}
        
        hosts = self.api.get_hosts_in_group(group["groupid"])
        if not hosts:
            logger.info(f"主机组 '{group_name}' 中没有主机")
            return {}
        
        all_results = {
            "group_name": group_name,
            "hosts": [],
            "summary": {
                "total_hosts": len(hosts),
                "non_template_items": 0,
                "non_template_triggers": 0,
                "disabled_items": 0,
                "disabled_triggers": 0,
                "template_items_with_non_template_triggers": 0
            }
        }
        
        for host in hosts:
            host_result = self._detect_host_issues(host)
            if host_result:
                all_results["hosts"].append(host_result)
                # 累计统计
                summary = all_results["summary"]
                host_summary = host_result.get("summary", {})
                summary["non_template_items"] += host_summary.get("non_template_items", 0)
                summary["non_template_triggers"] += host_summary.get("non_template_triggers", 0)
                summary["disabled_items"] += host_summary.get("disabled_items", 0)
                summary["disabled_triggers"] += host_summary.get("disabled_triggers", 0)
                summary["template_items_with_non_template_triggers"] += host_summary.get("template_items_with_non_template_triggers", 0)
        
        return all_results
    
    def _detect_host_issues(self, host: Dict) -> Dict:
        """检测单个主机的问题"""
        host_id = host["hostid"]
        host_name = host["name"]
        
        logger.info(f"检测主机: {host_name} (ID: {host_id})")
        
        # 获取主机的监控项和触发器
        items = self.api.get_host_items(host_id)
        triggers = self.api.get_host_triggers(host_id)
        
        # 分析结果
        result = {
            "host_name": host_name,
            "host_id": host_id,
            "templates": host.get("parentTemplates", []),
            "non_template_items": [],
            "non_template_triggers": [],
            "disabled_items": [],
            "disabled_triggers": [],
            "template_items_with_non_template_triggers": [],
            "summary": {
                "non_template_items": 0,
                "non_template_triggers": 0,
                "disabled_items": 0,
                "disabled_triggers": 0,
                "template_items_with_non_template_triggers": 0
            }
        }
        
        # 检测非模板监控项
        for item in items:
            # 非模板监控项：templateid 为 "0" 或空
            if not item.get("templateid") or item.get("templateid") == "0":
                item_info = {
                    "itemid": item["itemid"],
                    "name": item["name"],
                    "key_": item["key_"],
                    "status": "启用" if item.get("status", "0") == "0" else "禁用",
                    "type": self._get_item_type_name(item.get("type", "0")),
                    "delay": item.get("delay", "未知")
                }
                result["non_template_items"].append(item_info)
                result["summary"]["non_template_items"] += 1
            
            # 检测被禁用的监控项
            if item.get("status", "0") == "1":  # 1 表示禁用
                disabled_item_info = {
                    "itemid": item["itemid"],
                    "name": item["name"],
                    "key_": item["key_"],
                    "is_template_item": bool(item.get("templateid") and item.get("templateid") != "0"),
                    "template_id": item.get("templateid", "无")
                }
                result["disabled_items"].append(disabled_item_info)
                result["summary"]["disabled_items"] += 1
            
            # 检测模板监控项中的非模板触发器
            if item.get("templateid") and item.get("templateid") != "0":
                # 这是一个模板监控项，检查其触发器
                item_triggers = item.get("triggers", [])
                non_template_triggers_for_item = []
                
                for trigger in item_triggers:
                    if not trigger.get("templateid") or trigger.get("templateid") == "0":
                        non_template_triggers_for_item.append({
                            "triggerid": trigger["triggerid"],
                            "description": trigger["description"],
                            "status": "启用" if trigger.get("status", "0") == "0" else "禁用",
                            "priority": self._get_priority_name(trigger.get("priority", "0"))
                        })
                
                if non_template_triggers_for_item:
                    result["template_items_with_non_template_triggers"].append({
                        "item_name": item["name"],
                        "item_key": item["key_"],
                        "item_id": item["itemid"],
                        "template_id": item["templateid"],
                        "non_template_triggers": non_template_triggers_for_item
                    })
                    result["summary"]["template_items_with_non_template_triggers"] += len(non_template_triggers_for_item)
        
        # 检测非模板触发器
        for trigger in triggers:
            # 非模板触发器：templateid 为 "0" 或空
            if not trigger.get("templateid") or trigger.get("templateid") == "0":
                trigger_items = trigger.get("items", [])
                trigger_info = {
                    "triggerid": trigger["triggerid"],
                    "description": trigger["description"],
                    "expression": trigger["expression"],
                    "status": "启用" if trigger.get("status", "0") == "0" else "禁用",
                    "priority": self._get_priority_name(trigger.get("priority", "0")),
                    "items": [{
                        "item_name": item["name"],
                        "item_key": item["key_"],
                        "is_template_item": bool(item.get("templateid") and item.get("templateid") != "0")
                    } for item in trigger_items]
                }
                result["non_template_triggers"].append(trigger_info)
                result["summary"]["non_template_triggers"] += 1
            
            # 检测被禁用的触发器
            if trigger.get("status", "0") == "1":  # 1 表示禁用
                disabled_trigger_info = {
                    "triggerid": trigger["triggerid"],
                    "description": trigger["description"],
                    "is_template_trigger": bool(trigger.get("templateid") and trigger.get("templateid") != "0"),
                    "template_id": trigger.get("templateid", "无"),
                    "priority": self._get_priority_name(trigger.get("priority", "0"))
                }
                result["disabled_triggers"].append(disabled_trigger_info)
                result["summary"]["disabled_triggers"] += 1
        
        return result
    
    def _get_item_type_name(self, item_type: str) -> str:
        """获取监控项类型名称"""
        type_map = {
            "0": "Zabbix agent",
            "1": "SNMPv1 agent",
            "2": "Zabbix trapper",
            "3": "Simple check",
            "4": "SNMPv2 agent",
            "5": "Zabbix internal",
            "6": "SNMPv3 agent",
            "7": "Zabbix agent (active)",
            "8": "Zabbix aggregate",
            "9": "Web item",
            "10": "External check",
            "11": "Database monitor",
            "12": "IPMI agent",
            "13": "SSH agent",
            "14": "TELNET agent",
            "15": "Calculated",
            "16": "JMX agent",
            "17": "SNMP trap",
            "18": "Dependent item",
            "19": "HTTP agent",
            "20": "SNMP agent",
            "21": "Script"
        }
        return type_map.get(str(item_type), f"未知类型({item_type})")
    
    def _get_priority_name(self, priority: str) -> str:
        """获取优先级名称"""
        priority_map = {
            "0": "未分类",
            "1": "信息",
            "2": "警告",
            "3": "一般严重",
            "4": "严重",
            "5": "灾难"
        }
        return priority_map.get(str(priority), f"未知优先级({priority})")

class ReportGenerator:
    """报告生成器"""
    
    def generate_detailed_report(self, detection_result: Dict, output_file: str):
        """生成详细报告"""
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    '主机名', '主机ID', '问题类型', '项目ID', '项目名称', 
                    '项目键值', '状态', '优先级', '是否模板项', '模板ID', '描述'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                # 处理单主机或多主机结果
                hosts_data = []
                if "hosts" in detection_result:  # 主机组结果
                    hosts_data = detection_result["hosts"]
                elif "host_name" in detection_result:  # 单主机结果
                    hosts_data = [detection_result]
                
                for host_data in hosts_data:
                    host_name = host_data["host_name"]
                    host_id = host_data["host_id"]
                    
                    # 非模板监控项
                    for item in host_data.get("non_template_items", []):
                        writer.writerow({
                            '主机名': host_name,
                            '主机ID': host_id,
                            '问题类型': '非模板监控项',
                            '项目ID': item['itemid'],
                            '项目名称': item['name'],
                            '项目键值': item['key_'],
                            '状态': item['status'],
                            '优先级': '无',
                            '是否模板项': '否',
                            '模板ID': '无',
                            '描述': f"类型: {item['type']}, 采集间隔: {item['delay']}"
                        })
                    
                    # 非模板触发器
                    for trigger in host_data.get("non_template_triggers", []):
                        writer.writerow({
                            '主机名': host_name,
                            '主机ID': host_id,
                            '问题类型': '非模板触发器',
                            '项目ID': trigger['triggerid'],
                            '项目名称': trigger['description'],
                            '项目键值': '无',
                            '状态': trigger['status'],
                            '优先级': trigger['priority'],
                            '是否模板项': '否',
                            '模板ID': '无',
                            '描述': f"表达式: {trigger['expression']}"
                        })
                    
                    # 被禁用的监控项
                    for item in host_data.get("disabled_items", []):
                        writer.writerow({
                            '主机名': host_name,
                            '主机ID': host_id,
                            '问题类型': '被禁用的监控项',
                            '项目ID': item['itemid'],
                            '项目名称': item['name'],
                            '项目键值': item['key_'],
                            '状态': '禁用',
                            '优先级': '无',
                            '是否模板项': '是' if item['is_template_item'] else '否',
                            '模板ID': item['template_id'],
                            '描述': '监控项已被禁用'
                        })
                    
                    # 被禁用的触发器
                    for trigger in host_data.get("disabled_triggers", []):
                        writer.writerow({
                            '主机名': host_name,
                            '主机ID': host_id,
                            '问题类型': '被禁用的触发器',
                            '项目ID': trigger['triggerid'],
                            '项目名称': trigger['description'],
                            '项目键值': '无',
                            '状态': '禁用',
                            '优先级': trigger['priority'],
                            '是否模板项': '是' if trigger['is_template_trigger'] else '否',
                            '模板ID': trigger['template_id'],
                            '描述': '触发器已被禁用'
                        })
                    
                    # 模板监控项中的非模板触发器
                    for item_with_triggers in host_data.get("template_items_with_non_template_triggers", []):
                        for trigger in item_with_triggers['non_template_triggers']:
                            writer.writerow({
                                '主机名': host_name,
                                '主机ID': host_id,
                                '问题类型': '模板监控项中的非模板触发器',
                                '项目ID': trigger['triggerid'],
                                '项目名称': trigger['description'],
                                '项目键值': item_with_triggers['item_key'],
                                '状态': trigger['status'],
                                '优先级': trigger['priority'],
                                '是否模板项': '否',
                                '模板ID': '无',
                                '描述': f"关联的模板监控项: {item_with_triggers['item_name']}"
                            })
            
            logger.info(f"详细报告已生成: {output_file}")
            
        except Exception as e:
            logger.error(f"生成详细报告失败: {e}")
    
    def generate_summary_report(self, detection_result: Dict, output_file: str):
        """生成汇总报告"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write("Zabbix 检测汇总报告\n")
                f.write("=" * 50 + "\n\n")
                f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                
                if "group_name" in detection_result:
                    # 主机组报告
                    f.write(f"检测范围: 主机组 '{detection_result['group_name']}'\n")
                    summary = detection_result["summary"]
                    f.write(f"主机总数: {summary['total_hosts']}\n\n")
                elif "host_name" in detection_result:
                    # 单主机报告
                    f.write(f"检测范围: 主机 '{detection_result['host_name']}'\n")
                    summary = detection_result["summary"]
                    f.write("主机总数: 1\n\n")
                else:
                    f.write("检测范围: 未知\n\n")
                    return
                
                f.write("检测结果汇总:\n")
                f.write("-" * 30 + "\n")
                f.write(f"非模板监控项: {summary['non_template_items']} 个\n")
                f.write(f"非模板触发器: {summary['non_template_triggers']} 个\n")
                f.write(f"被禁用的监控项: {summary['disabled_items']} 个\n")
                f.write(f"被禁用的触发器: {summary['disabled_triggers']} 个\n")
                f.write(f"模板监控项中的非模板触发器: {summary['template_items_with_non_template_triggers']} 个\n\n")
                
                # 如果是主机组报告，显示每个主机的详情
                if "hosts" in detection_result:
                    f.write("各主机详情:\n")
                    f.write("-" * 30 + "\n")
                    for host_data in detection_result["hosts"]:
                        host_summary = host_data["summary"]
                        f.write(f"\n主机: {host_data['host_name']} (ID: {host_data['host_id']})\n")
                        f.write(f"  - 非模板监控项: {host_summary['non_template_items']} 个\n")
                        f.write(f"  - 非模板触发器: {host_summary['non_template_triggers']} 个\n")
                        f.write(f"  - 被禁用的监控项: {host_summary['disabled_items']} 个\n")
                        f.write(f"  - 被禁用的触发器: {host_summary['disabled_triggers']} 个\n")
                        f.write(f"  - 模板监控项中的非模板触发器: {host_summary['template_items_with_non_template_triggers']} 个\n")
                        
                        # 显示关联的模板
                        templates = host_data.get("templates", [])
                        if templates:
                            f.write(f"  - 关联模板: {', '.join([t['name'] for t in templates])}\n")
            
            logger.info(f"汇总报告已生成: {output_file}")
            
        except Exception as e:
            logger.error(f"生成汇总报告失败: {e}")

def main():
    """主函数"""
    if len(sys.argv) < 3:
        print("使用方法:")
        print("1. 按主机检测:")
        print("   python3 zabbix_detector.py host <主机名>")
        print("2. 按主机组检测:")
        print("   python3 zabbix_detector.py hostgroup <主机组名>")
        print("")
        print("功能说明:")
        print("- 检测非模板监控项")
        print("- 检测非模板触发器")
        print("- 检测被禁用的监控项和触发器")
        print("- 检测模板监控项中的非模板触发器")
        print("")
        print("示例:")
        print("   python3 zabbix_detector.py host 'TestHost01-Linux'")
        print("   python3 zabbix_detector.py hostgroup '测试主机组A - 模板替换'")
        sys.exit(1)
    
    try:
        config = ZabbixConfig()
        
        with ZabbixAPI(config) as api:
            detector = ZabbixDetector(api)
            report_generator = ReportGenerator()
            
            mode = sys.argv[1]
            identifier = sys.argv[2]
            
            # 生成时间戳用于文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            if mode == "host":
                result = detector.detect_by_host(identifier)
                if result:
                    # 生成报告
                    detail_file = f"zabbix_detection_detail_{identifier}_{timestamp}.csv"
                    summary_file = f"zabbix_detection_summary_{identifier}_{timestamp}.txt"
                    
                    report_generator.generate_detailed_report(result, detail_file)
                    report_generator.generate_summary_report(result, summary_file)
                    
                    # 显示汇总信息
                    summary = result["summary"]
                    print(f"\n检测完成 - 主机: {identifier}")
                    print("=" * 50)
                    print(f"非模板监控项: {summary['non_template_items']} 个")
                    print(f"非模板触发器: {summary['non_template_triggers']} 个")
                    print(f"被禁用的监控项: {summary['disabled_items']} 个")
                    print(f"被禁用的触发器: {summary['disabled_triggers']} 个")
                    print(f"模板监控项中的非模板触发器: {summary['template_items_with_non_template_triggers']} 个")
                    print(f"\n详细报告: {detail_file}")
                    print(f"汇总报告: {summary_file}")
                    
            elif mode == "hostgroup":
                result = detector.detect_by_hostgroup(identifier)
                if result:
                    # 生成报告
                    detail_file = f"zabbix_detection_detail_{identifier.replace(' ', '_')}_{timestamp}.csv"
                    summary_file = f"zabbix_detection_summary_{identifier.replace(' ', '_')}_{timestamp}.txt"
                    
                    report_generator.generate_detailed_report(result, detail_file)
                    report_generator.generate_summary_report(result, summary_file)
                    
                    # 显示汇总信息
                    summary = result["summary"]
                    print(f"\n检测完成 - 主机组: {identifier}")
                    print("=" * 50)
                    print(f"检测主机数: {summary['total_hosts']} 个")
                    print(f"非模板监控项: {summary['non_template_items']} 个")
                    print(f"非模板触发器: {summary['non_template_triggers']} 个")
                    print(f"被禁用的监控项: {summary['disabled_items']} 个")
                    print(f"被禁用的触发器: {summary['disabled_triggers']} 个")
                    print(f"模板监控项中的非模板触发器: {summary['template_items_with_non_template_triggers']} 个")
                    print(f"\n详细报告: {detail_file}")
                    print(f"汇总报告: {summary_file}")
            else:
                print("错误: 无效的检测模式，请使用 'host' 或 'hostgroup'")
                sys.exit(1)
                
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()