export async function navigate(page,label){
 const aliases={'系统管理':'平台设置','任务示例':'任务示例与文档'};
 label=aliases[label] || label;
 if(['执行队列','执行矩阵'].includes(label)){
  await page.getByRole('navigation',{name:'工作区导航'}).getByRole('button',{name:'执行矩阵',exact:true}).click();
  await page.getByRole('navigation',{name:'执行矩阵分栏'}).getByRole('button',{name:label==='执行队列'?'执行队列':'当日轨迹',exact:true}).click();
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
