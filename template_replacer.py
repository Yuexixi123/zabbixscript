#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zabbix 模板替换工具
功能：
1. 在指定主机组中查找使用特定模板的主机
2. 将旧模板替换为新模板
3. 支持通过主机ID或主机名进行操作
4. 生成操作日志
5. 检测和删除迁移后的非模板触发器
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
        logging.FileHandler('template_replace.log', encoding='utf-8'),
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
    
    def get_template_by_name(self, template_name: str) -> Optional[Dict]:
        """根据名称获取模板"""
        templates = self._call_api("template.get", {
            "filter": {"name": template_name},
            "output": ["templateid", "name"]
        })
        return templates[0] if templates else None
    
    def get_hosts_in_group_with_template(self, group_id: str, template_id: str) -> List[Dict]:
        """获取主机组中使用指定模板的主机"""
        return self._call_api("host.get", {
            "output": ["hostid", "name"],
            "groupids": group_id,
            "templateids": template_id,
            "selectParentTemplates": ["templateid", "name"]
        })
    
    def get_host_by_id(self, host_id: str) -> Optional[Dict]:
        """根据ID获取主机"""
        hosts = self._call_api("host.get", {
            "output": ["hostid", "name"],
            "hostids": host_id,
            "selectParentTemplates": ["templateid", "name"]
        })
        return hosts[0] if hosts else None
    
    def get_host_by_name(self, host_name: str) -> Optional[Dict]:
        """根据名称获取主机"""
        hosts = self._call_api("host.get", {
            "output": ["hostid", "name"],
            "filter": {"name": host_name},
            "selectParentTemplates": ["templateid", "name"]
        })
        return hosts[0] if hosts else None
    
    def get_host_non_template_triggers(self, host_id: str) -> List[Dict]:
        """获取主机的非模板触发器"""
        try:
            triggers = self._call_api("trigger.get", {
                "output": ["triggerid", "description", "expression", "priority", "status", "templateid"],
                "hostids": host_id,
                "inherited": False,  # 只获取非继承的触发器
                "filter": {"flags": 0},  # 只获取普通触发器（非发现规则生成）
                "selectItems": ["itemid", "name", "key_"]
            })
            
            # 进一步过滤，确保是非模板触发器
            non_template_triggers = []
            for trigger in triggers:
                # 检查 templateid 字段，如果为 "0" 或空，则为非模板触发器
                if not trigger.get("templateid") or trigger.get("templateid") == "0":
                    non_template_triggers.append(trigger)
            
            return non_template_triggers
            
        except Exception as e:
            logger.error(f"获取主机 {host_id} 的非模板触发器失败: {e}")
            return []
    
    def delete_trigger(self, trigger_id: str) -> bool:
        """删除触发器"""
        try:
            self._call_api("trigger.delete", [trigger_id])
            return True
        except Exception as e:
            logger.error(f"删除触发器 {trigger_id} 失败: {e}")
            return False
    
    def replace_host_template(self, host_id: str, old_template_id: str, new_template_id: str) -> bool:
        """替换主机模板"""
        try:
            # 获取主机当前的所有模板
            host = self.get_host_by_id(host_id)
            if not host:
                logger.error(f"主机 {host_id} 不存在")
                return False
            
            current_templates = host.get("parentTemplates", [])
            
            # 构建新的模板列表
            new_templates = []
            template_replaced = False
            
            for template in current_templates:
                if template["templateid"] == old_template_id:
                    # 替换旧模板为新模板
                    new_templates.append({"templateid": new_template_id})
                    template_replaced = True
                    logger.info(f"主机 {host['name']} 模板 {template['name']} 将被替换")
                else:
                    # 保留其他模板
                    new_templates.append({"templateid": template["templateid"]})
            
            if not template_replaced:
                logger.warning(f"主机 {host['name']} 未使用指定的旧模板")
                return False
            
            # 执行模板替换
            self._call_api("host.update", {
                "hostid": host_id,
                "templates": new_templates
            })
            
            logger.info(f"主机 {host['name']} 模板替换成功")
            return True
            
        except Exception as e:
            logger.error(f"替换主机 {host_id} 模板失败: {e}")
            return False

class TriggerAnalyzer:
    """触发器分析器"""
    
    def __init__(self, api: ZabbixAPI):
        self.api = api
    
    def analyze_host_triggers(self, host_id: str, host_name: str) -> List[Dict]:
        """分析主机的非模板触发器"""
        triggers = self.api.get_host_non_template_triggers(host_id)
        
        trigger_info = []
        for trigger in triggers:
            # 获取触发器关联的监控项信息
            items_info = []
            for item in trigger.get("items", []):
                items_info.append({
                    "item_name": item.get("name", "未知监控项"),
                    "item_key": item.get("key_", "未知键值")
                })
            
            trigger_info.append({
                "host_name": host_name,
                "host_id": host_id,
                "trigger_id": trigger["triggerid"],
                "description": trigger.get("description", "无描述"),
                "expression": trigger.get("expression", "无表达式"),
                "priority": self._get_priority_name(trigger.get("priority", "0")),
                "status": "启用" if trigger.get("status", "0") == "0" else "禁用",
                "items": items_info
            })
        
        return trigger_info
    
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
        return priority_map.get(str(priority), "未知")
    
    def generate_trigger_report(self, trigger_data: List[Dict], output_file: str):
        """生成触发器报告"""
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    '主机名', '主机ID', '触发器ID', '触发器描述', 
                    '表达式', '优先级', '状态', '监控项名称', '监控项键值'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for trigger in trigger_data:
                    if trigger['items']:
                        # 如果有监控项，为每个监控项写一行
                        for item in trigger['items']:
                            writer.writerow({
                                '主机名': trigger['host_name'],
                                '主机ID': trigger['host_id'],
                                '触发器ID': trigger['trigger_id'],
                                '触发器描述': trigger['description'],
                                '表达式': trigger['expression'],
                                '优先级': trigger['priority'],
                                '状态': trigger['status'],
                                '监控项名称': item['item_name'],
                                '监控项键值': item['item_key']
                            })
                    else:
                        # 如果没有监控项，写一行空的监控项信息
                        writer.writerow({
                            '主机名': trigger['host_name'],
                            '主机ID': trigger['host_id'],
                            '触发器ID': trigger['trigger_id'],
                            '触发器描述': trigger['description'],
                            '表达式': trigger['expression'],
                            '优先级': trigger['priority'],
                            '状态': trigger['status'],
                            '监控项名称': '无关联监控项',
                            '监控项键值': '无关联监控项'
                        })
            
            logger.info(f"触发器报告已生成: {output_file}")
            
        except Exception as e:
            logger.error(f"生成触发器报告失败: {e}")

class TemplateReplacer:
    """模板替换器"""
    
    def __init__(self, config: ZabbixConfig):
        self.config = config
    
    def replace_templates_in_group(self, group_name: str, old_template_name: str, new_template_name: str, check_triggers: bool = False):
        """在指定主机组中替换模板"""
        logger.info(f"开始在主机组 '{group_name}' 中替换模板")
        logger.info(f"旧模板: {old_template_name}")
        logger.info(f"新模板: {new_template_name}")
        
        try:
            with ZabbixAPI(self.config) as api:
                # 获取主机组
                group = api.get_hostgroup_by_name(group_name)
                if not group:
                    logger.error(f"主机组 '{group_name}' 不存在")
                    return
                
                # 获取模板
                old_template = api.get_template_by_name(old_template_name)
                if not old_template:
                    logger.error(f"旧模板 '{old_template_name}' 不存在")
                    return
                
                new_template = api.get_template_by_name(new_template_name)
                if not new_template:
                    logger.error(f"新模板 '{new_template_name}' 不存在")
                    return
                
                # 获取使用旧模板的主机
                hosts = api.get_hosts_in_group_with_template(
                    group["groupid"], 
                    old_template["templateid"]
                )
                
                if not hosts:
                    logger.info(f"主机组 '{group_name}' 中没有使用模板 '{old_template_name}' 的主机")
                    return
                
                logger.info(f"找到 {len(hosts)} 个主机需要替换模板")
                
                # 替换每个主机的模板
                success_count = 0
                replaced_hosts = []
                
                for host in hosts:
                    if api.replace_host_template(
                        host["hostid"], 
                        old_template["templateid"], 
                        new_template["templateid"]
                    ):
                        success_count += 1
                        replaced_hosts.append(host)
                
                logger.info(f"模板替换完成: {success_count}/{len(hosts)} 个主机成功")
                
                # 如果启用触发器检查
                if check_triggers and replaced_hosts:
                    self._check_non_template_triggers(api, replaced_hosts)
                
        except Exception as e:
            logger.error(f"模板替换过程中发生错误: {e}")
    
    def replace_template_for_host(self, host_identifier: str, old_template_name: str, new_template_name: str, by_id: bool = False, check_triggers: bool = False):
        """为指定主机替换模板"""
        identifier_type = "ID" if by_id else "名称"
        logger.info(f"开始为主机 {identifier_type} '{host_identifier}' 替换模板")
        logger.info(f"旧模板: {old_template_name}")
        logger.info(f"新模板: {new_template_name}")
        
        try:
            with ZabbixAPI(self.config) as api:
                # 获取主机
                if by_id:
                    host = api.get_host_by_id(host_identifier)
                else:
                    host = api.get_host_by_name(host_identifier)
                
                if not host:
                    logger.error(f"主机 {identifier_type} '{host_identifier}' 不存在")
                    return
                
                # 获取模板
                old_template = api.get_template_by_name(old_template_name)
                if not old_template:
                    logger.error(f"旧模板 '{old_template_name}' 不存在")
                    return
                
                new_template = api.get_template_by_name(new_template_name)
                if not new_template:
                    logger.error(f"新模板 '{new_template_name}' 不存在")
                    return
                
                # 替换模板
                if api.replace_host_template(
                    host["hostid"], 
                    old_template["templateid"], 
                    new_template["templateid"]
                ):
                    logger.info(f"主机 '{host['name']}' 模板替换成功")
                    
                    # 如果启用触发器检查
                    if check_triggers:
                        self._check_non_template_triggers(api, [host])
                else:
                    logger.error(f"主机 '{host['name']}' 模板替换失败")
                
        except Exception as e:
            logger.error(f"模板替换过程中发生错误: {e}")
    
    def _check_non_template_triggers(self, api: ZabbixAPI, hosts: List[Dict]):
        """检查非模板触发器"""
        logger.info("开始检查迁移后的非模板触发器...")
        
        analyzer = TriggerAnalyzer(api)
        all_trigger_data = []
        
        for host in hosts:
            trigger_data = analyzer.analyze_host_triggers(host["hostid"], host["name"])
            all_trigger_data.extend(trigger_data)
        
        if all_trigger_data:
            # 生成报告文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_file = f"non_template_triggers_{timestamp}.csv"
            analyzer.generate_trigger_report(all_trigger_data, report_file)
            
            logger.info(f"发现 {len(all_trigger_data)} 个非模板触发器")
            logger.info(f"详细报告已保存到: {report_file}")
            
            # 询问是否删除
            self._prompt_trigger_deletion(api, all_trigger_data, report_file)
        else:
            logger.info("未发现非模板触发器")
    
    def _prompt_trigger_deletion(self, api: ZabbixAPI, trigger_data: List[Dict], report_file: str):
        """提示用户确认删除触发器"""
        print("\n" + "="*60)
        print("检测到非模板触发器！")
        print(f"详细信息请查看报告文件: {report_file}")
        print(f"共发现 {len(trigger_data)} 个非模板触发器")
        print("="*60)
        
        # 显示前5个触发器的简要信息
        print("\n前5个触发器预览:")
        for i, trigger in enumerate(trigger_data[:5]):
            print(f"{i+1}. 主机: {trigger['host_name']} | 触发器: {trigger['description']} | 优先级: {trigger['priority']}")
        
        if len(trigger_data) > 5:
            print(f"... 还有 {len(trigger_data) - 5} 个触发器，详见报告文件")
        
        print("\n请选择操作:")
        print("1. 删除所有非模板触发器")
        print("2. 手动选择删除")
        print("3. 跳过删除")
        
        try:
            choice = input("\n请输入选择 (1/2/3): ").strip()
            
            if choice == "1":
                self._delete_all_triggers(api, trigger_data)
            elif choice == "2":
                self._selective_delete_triggers(api, trigger_data)
            elif choice == "3":
                logger.info("跳过删除操作")
            else:
                logger.warning("无效选择，跳过删除操作")
                
        except KeyboardInterrupt:
            logger.info("\n操作被用户取消")
        except Exception as e:
            logger.error(f"处理用户输入时发生错误: {e}")
    
    def _delete_all_triggers(self, api: ZabbixAPI, trigger_data: List[Dict]):
        """删除所有触发器"""
        logger.info("开始删除所有非模板触发器...")
        
        success_count = 0
        for trigger in trigger_data:
            if api.delete_trigger(trigger["trigger_id"]):
                success_count += 1
                logger.info(f"已删除触发器: {trigger['description']} (主机: {trigger['host_name']})")
        
        logger.info(f"删除完成: {success_count}/{len(trigger_data)} 个触发器成功删除")
    
    def _selective_delete_triggers(self, api: ZabbixAPI, trigger_data: List[Dict]):
        """选择性删除触发器"""
        print("\n请输入要删除的触发器编号 (用逗号分隔，如: 1,3,5):")
        
        # 显示所有触发器
        for i, trigger in enumerate(trigger_data):
            print(f"{i+1}. 主机: {trigger['host_name']} | 触发器: {trigger['description']} | 优先级: {trigger['priority']}")
        
        try:
            indices_input = input("\n请输入编号: ").strip()
            if not indices_input:
                logger.info("未选择任何触发器")
                return
            
            indices = [int(x.strip()) - 1 for x in indices_input.split(',')]
            
            success_count = 0
            for index in indices:
                if 0 <= index < len(trigger_data):
                    trigger = trigger_data[index]
                    if api.delete_trigger(trigger["trigger_id"]):
                        success_count += 1
                        logger.info(f"已删除触发器: {trigger['description']} (主机: {trigger['host_name']})")
                else:
                    logger.warning(f"无效编号: {index + 1}")
            
            logger.info(f"删除完成: {success_count}/{len(indices)} 个选中的触发器成功删除")
            
        except ValueError:
            logger.error("输入格式错误，请输入有效的数字")
        except Exception as e:
            logger.error(f"处理选择时发生错误: {e}")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("使用方法:")
        print("1. 替换主机组中的模板:")
        print("   python3 template_replacer.py group <主机组名> <旧模板名> <新模板名> [--check-triggers]")
        print("2. 替换指定主机的模板(按名称):")
        print("   python3 template_replacer.py host-name <主机名> <旧模板名> <新模板名> [--check-triggers]")
        print("3. 替换指定主机的模板(按ID):")
        print("   python3 template_replacer.py host-id <主机ID> <旧模板名> <新模板名> [--check-triggers]")
        print("4. 仅检查非模板触发器:")
        print("   python3 template_replacer.py check-triggers <主机名或主机组名> [--by-group]")
        print("")
        print("参数说明:")
        print("   --check-triggers: 在模板替换后检查并可选择删除非模板触发器")
        print("   --by-group: 与 check-triggers 配合使用，按主机组检查")
        print("")
        print("示例:")
        print("   python3 template_replacer.py group '下线' 'Template xacb Linux' 'Template xacb Linux nocritical system' --check-triggers")
        sys.exit(1)
    
    try:
        config = ZabbixConfig()
        replacer = TemplateReplacer(config)
        
        mode = sys.argv[1]
        check_triggers = "--check-triggers" in sys.argv
        by_group = "--by-group" in sys.argv
        
        if mode == "group" and len(sys.argv) >= 5:
            group_name = sys.argv[2]
            old_template = sys.argv[3]
            new_template = sys.argv[4]
            replacer.replace_templates_in_group(group_name, old_template, new_template, check_triggers)
            
        elif mode == "host-name" and len(sys.argv) >= 5:
            host_name = sys.argv[2]
            old_template = sys.argv[3]
            new_template = sys.argv[4]
            replacer.replace_template_for_host(host_name, old_template, new_template, by_id=False, check_triggers=check_triggers)
            
        elif mode == "host-id" and len(sys.argv) >= 5:
            host_id = sys.argv[2]
            old_template = sys.argv[3]
            new_template = sys.argv[4]
            replacer.replace_template_for_host(host_id, old_template, new_template, by_id=True, check_triggers=check_triggers)
            
        elif mode == "check-triggers" and len(sys.argv) >= 3:
            identifier = sys.argv[2]
            
            with ZabbixAPI(config) as api:
                analyzer = TriggerAnalyzer(api)
                all_trigger_data = []
                
                if by_group:
                    # 按主机组检查
                    group = api.get_hostgroup_by_name(identifier)
                    if not group:
                        logger.error(f"主机组 '{identifier}' 不存在")
                        return
                    
                    hosts = api._call_api("host.get", {
                        "output": ["hostid", "name"],
                        "groupids": group["groupid"]
                    })
                    
                    for host in hosts:
                        trigger_data = analyzer.analyze_host_triggers(host["hostid"], host["name"])
                        all_trigger_data.extend(trigger_data)
                else:
                    # 按主机名检查
                    host = api.get_host_by_name(identifier)
                    if not host:
                        logger.error(f"主机 '{identifier}' 不存在")
                        return
                    
                    all_trigger_data = analyzer.analyze_host_triggers(host["hostid"], host["name"])
                
                if all_trigger_data:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    report_file = f"non_template_triggers_{timestamp}.csv"
                    analyzer.generate_trigger_report(all_trigger_data, report_file)
                    
                    logger.info(f"发现 {len(all_trigger_data)} 个非模板触发器")
                    logger.info(f"详细报告已保存到: {report_file}")
                    
                    replacer._prompt_trigger_deletion(api, all_trigger_data, report_file)
                else:
                    logger.info("未发现非模板触发器")
            
        else:
            print("参数错误，请查看使用方法")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"程序执行失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()