export async function navigate(page,label){
 const aliases={'系统管理':'平台设置','任务示例':'任务示例与文档'};
 label=aliases[label] || label;
 if(['执行队列','执行矩阵','执行记录'].includes(label)){
  await page.getByRole('navigation',{name:'工作区导航'}).getByRole('button',{name:'任务执行',exact:true}).click();
  await page.getByRole('navigation',{name:'任务执行分栏'}).getByRole('button',{name:label==='执行矩阵'?'当日轨迹':label,exact:true}).click();
  return;
 }
 if(['数据库连接','依赖仓库'].includes(label)){
  await navigate(page,'平台设置');
  await page.getByRole('button',{name:'连接与依赖',exact:true}).click();
  await page.getByRole('navigation',{name:'平台设置分栏',exact:true}).getByRole('button',{name:label,exact:true}).click();
 }else if(['平台设置','平台事件','任务示例与文档'].includes(label)){
  await page.getByRole('button',{name:/账户菜单$/}).click();
  await page.getByRole('menuitem',{name:label,exact:true}).click();
 }else await page.getByRole('button',{name:label,exact:true}).first().click();
}

export async function detailTab(page,name){
 const group={'说明与配置':'概览','执行流程':'概览','执行与输出':'执行','执行记录':'执行','运行策略':'配置','配置历史':'配置','查看代码':'发布','代码版本':'发布','DDL 与标签':'发布','连接授权':'安全与审计','操作记录':'安全与审计'}[name];
 const dialog=page.locator('.task-workbench');
 const button=dialog.getByRole('navigation',{name:'任务工作区'}).getByRole('button',{name:group,exact:true});
 if(await button.getAttribute('aria-pressed')!=='true')await button.click();
 // A rejected unsaved-changes prompt deliberately leaves the old group active.
 const tab=dialog.getByRole('tab',{name,exact:true});if(await tab.isVisible())await tab.click();
}
