import{_ as f,l as x,o as _,c as E,a as r,t as l,I as S,d as w,i as R,n as N,F as v,r as D,s as A,q as I,G as L,b as T,k as b,e as g}from"./index-Co0t40Zt.js";function h({kind:e="business",connectionId:n="business_db",dialect:c="postgresql"}={}){if(e==="platform")return B();const u=JSON.stringify(String(n||"business_db")),s=c==="clickhouse",a=p=>`from app.common.database import NewDB

with NewDB(${u}) as db:
${y(p)}`,i="仅在隔离的测试业务库运行写入示例，先创建 demo_db_usage 表；重复插入前请更换示例 ID。",m=s?"CREATE TABLE IF NOT EXISTS demo_db_usage (id UInt64, status String) ENGINE = MergeTree ORDER BY id":"CREATE TABLE IF NOT EXISTS demo_db_usage (id INTEGER PRIMARY KEY, status VARCHAR(40))",d=s?"ALTER TABLE demo_db_usage UPDATE status = :status WHERE id = :id SETTINGS mutations_sync = 1":"UPDATE demo_db_usage SET status = :status WHERE id = :id",o=s?"ALTER TABLE demo_db_usage DELETE WHERE id = :id SETTINGS mutations_sync = 1":"DELETE FROM demo_db_usage WHERE id = :id",t=[{id:"setup",title:"准备测试表",description:"一次性准备以下示例使用的独立表，不操作平台系统表。",code:a(`db.execute(${JSON.stringify(m)})`),note:i},{id:"query",title:"查询",description:"参数由驱动绑定；as_dict=True 返回字典列表。",code:a(`rows = db.query(
    "SELECT id, status FROM demo_db_usage WHERE id = ?",
    (1,),
    as_dict=True,
)
print(rows)`),note:"值用参数传入，不使用字符串拼接。表名、列名不能作为值参数绑定，动态标识符必须使用白名单。"},{id:"insert",title:"新增",description:"单条写入成功后自动提交。",code:a(`affected = db.execute(
    "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",
    {"id": 1, "status": "pending"},
)
print(affected)`),note:`${i} 返回值是驱动提供的影响行数，个别驱动可能返回 -1，不能把它当作失败。`},{id:"update",title:"修改",description:s?"ClickHouse 使用 ALTER TABLE mutation；等待本次 mutation 完成。":"带条件更新，避免误改整表。",code:a(`db.execute(
    ${JSON.stringify(d)},
    {"id": 1, "status": "done"},
)`),note:s?"ClickHouse mutation 会重写数据部分，可能耗时；不是普通事务，也无法回滚。mutations_sync=1 等待当前副本完成。":i},{id:"delete",title:"删除",description:s?"使用带条件的 ClickHouse 删除 mutation。":"删除前确认筛选范围；这里仅删除示例记录 3。",code:a(`db.execute(
    ${JSON.stringify(o)},
    {"id": 3},
)`),note:i},{id:"batch",title:"批量写入",description:"使用 executemany，一次提交多行绑定参数。",code:a(`rows = [
    {"id": 2, "status": "pending"},
    {"id": 3, "status": "pending"},
]
db.executemany(
    "INSERT INTO demo_db_usage (id, status) VALUES (:id, :status)",
    rows,
)`),note:s?"ClickHouse 不支持回滚。大批量数据请分批处理，具体批次大小按行宽和生产监测调整。":"大批量数据请分批处理；同一个显式 transaction() 中的多批写入会统一提交或回滚。"}];return s||t.push({id:"transaction",title:"事务",description:"整段成功才提交，任意语句抛错则自动回滚。",code:a(`with db.transaction():
    db.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("processing", 1),
    )
    db.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("processing", 2),
    )`),note:"MySQL 表须使用支持事务的存储引擎。不要在事务内部吞掉异常，也不要在同步事务中调用 async_* 方法。DDL 的提交行为由具体数据库决定。"}),t.push({id:"async",title:"异步读写",description:"独占线程完成每次数据库操作，等待 SQL 时不阻塞事件循环。",code:`import asyncio
from app.common.database import NewDB

async def main():
    async with NewDB(${u}) as db:
        await db.async_execute(
            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
            (101, "pending"),
        )
        await db.async_executemany(
            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
            [(102, "pending"), (103, "pending")],
        )
        rows = await db.async_query(
            "SELECT id, status FROM demo_db_usage WHERE id = ?",
            (101,),
            as_dict=True,
        )
        print(rows)

if __name__ == "__main__":
    asyncio.run(main())`,note:"每进程最多 4 个 SQL 工作线程、16 个待完成操作（含运行中），超额提交会报错。连接池限额仍生效；取消 await 不保证取消 SQL 或回滚，不能据此自动重试写入。已有事件循环中直接 await main()。"}),s||t.push({id:"async-transaction",title:"异步事务",description:"同步回调中的整段事务在同一个线程、同一连接执行。",code:`import asyncio
from app.common.database import NewDB

def update_batch(tx):
    # tx 是工作线程独占的 NewDB，回调中不能使用 await。
    tx.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("done", 101),
    )
    tx.execute(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        ("done", 102),
    )
    return tx.query(
        "SELECT id, status FROM demo_db_usage WHERE id IN (?, ?)",
        (101, 102),
        as_dict=True,
    )

async def main():
    async with NewDB(${u}) as db:
        rows = await db.async_transaction(update_batch)
        print(rows)

if __name__ == "__main__":
    asyncio.run(main())`,note:"回调正常返回才提交，异常自动回滚。不要捕获外部 db 在回调中使用，不要返回连接或游标。运行中的回调即使 await 被取消，仍会继续执行并最终释放连接。"}),t}function y(e){return e.split(`
`).map(n=>n?`    ${n}`:"").join(`
`)}function B(){const e="仅供平台内部开发与维护。任务代码必须使用获得授权的 NewDB 业务连接，不得使用 GaussDB 访问平台库。写入示例请在隔离测试环境运行。",n=c=>`from app.bootstrap.database import GaussDB

with GaussDB() as db:
${y(c)}`;return[{id:"setup",title:"准备测试表",description:"使用独立示例表，不修改任何 wfs_* 平台系统表。",code:n(`db.execute_sql(
    "CREATE TABLE IF NOT EXISTS demo_db_usage (id INTEGER PRIMARY KEY, status VARCHAR(40))"
)`),note:e},{id:"query",title:"查询",description:"return_json=True 返回字典列表，否则返回元组列表。",code:n(`rows = db.execute_query_sql(
    "SELECT id, status FROM demo_db_usage WHERE id = ?",
    params=(1,),
    return_json=True,
)
print(rows)`),note:e},{id:"insert",title:"新增",description:"平台连接默认自动提交；execute_sql 不返回影响行数。",code:n(`db.execute_sql(
    "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
    params=(1, "pending"),
)`),note:e},{id:"update",title:"修改",description:"通过参数绑定传递值，并明确更新条件。",code:n(`db.execute_sql(
    "UPDATE demo_db_usage SET status = ? WHERE id = ?",
    params=("done", 1),
)`),note:e},{id:"delete",title:"删除",description:"先核对记录范围，再执行带条件的删除。",code:n('db.execute_sql("DELETE FROM demo_db_usage WHERE id = ?", params=(3,))'),note:e},{id:"batch",title:"同一事务多行写入",description:"平台内部接口没有 executemany；少量多行写入可在同一事务循环处理。",code:n(`db.begin_transaction()
try:
    for row in [(2, "pending"), (3, "pending")]:
        db.execute_sql(
            "INSERT INTO demo_db_usage (id, status) VALUES (?, ?)",
            params=row,
        )
    db.set_commit()
except BaseException:
    db.set_rollback()
    raise`),note:e},{id:"transaction",title:"事务",description:"显式开始事务，成功提交，异常回滚。",code:n(`db.begin_transaction()
try:
    db.execute_sql(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        params=("processing", 1),
    )
    db.execute_sql(
        "UPDATE demo_db_usage SET status = ? WHERE id = ?",
        params=("processing", 2),
    )
    db.set_commit()
except BaseException:
    db.set_rollback()
    raise`),note:e},{id:"async",title:"异步调用",description:"将连接创建、整段事务和关闭都放到同一个工作线程。",code:`import asyncio
from app.bootstrap.database import GaussDB

def update_and_read():
    # 在工作线程中创建及关闭句柄，不传入外部连接。
    with GaussDB() as db:
        db.begin_transaction()
        try:
            db.execute_sql(
                "UPDATE demo_db_usage SET status = ? WHERE id = ?",
                params=("done", 1),
            )
            rows = db.execute_query_sql(
                "SELECT id, status FROM demo_db_usage WHERE id = ?",
                params=(1,),
                return_json=True,
            )
            db.set_commit()
            return rows
        except BaseException:
            db.set_rollback()
            raise

async def main():
    rows = await asyncio.to_thread(update_and_read)
    print(rows)

if __name__ == "__main__":
    asyncio.run(main())`,note:`${e} 这是同步驱动的线程卸载，并非原生异步驱动。取消 await 不会中止已开始的 SQL；批量异步调用请限制并发，避免占满平台连接池。`}]}const k={class:"surface-card database-usage-examples"},H={class:"examples-heading"},q={class:"hint"},O=["value"],C={key:0,class:"hint"},U={key:1,class:"inline-alert warning",role:"status"},W={__name:"DatabaseUsageExamples",props:{kind:{type:String,default:"business"},connectionId:String,dialect:String},setup(e){const n=e,c=g(()=>h({kind:n.kind,connectionId:n.connectionId,dialect:n.dialect})),u=b("query"),s=b(!1),a=b(""),i=g(()=>c.value.find(d=>d.id===u.value)||c.value[0]);x(i,()=>{s.value=!1,a.value="",c.value.some(d=>d.id===u.value)||(u.value=c.value[0]?.id)});async function m(){s.value=!1,a.value="";const d=i.value?.code;if(d)try{if(navigator.clipboard?.writeText)try{await navigator.clipboard.writeText(d),s.value=!0;return}catch{}const o=document.activeElement,t=document.createElement("textarea");t.value=d,t.setAttribute("readonly",""),t.style.cssText="position:fixed;left:-9999px;top:0;",document.body.appendChild(t);let p=!1;try{t.select(),p=document.execCommand("copy")}finally{t.remove(),o?.focus()}if(!p)throw new Error("copy");s.value=!0}catch{a.value="未能自动复制，请选中下方代码手动复制。"}}return(d,o)=>(_(),E("section",k,[r("div",H,[r("h3",null,l(e.kind==="platform"?"平台数据库开发示例":"任务中的统一用法"),1),r("button",{type:"button",class:"btn",onClick:m},l(s.value?"已复制":"复制示例"),1)]),r("p",q,l(e.kind==="platform"?"仅用于平台内部开发，任务代码必须使用“任务示例与文档”中的 NewDB 示例，不能访问平台内部库。":"先在任务详情中授权连接，再通过 NewDB 使用连接标识。直接配置与 Nacos 来源使用相同写法。"),1),S(d.$slots,"settings",{},void 0,!0),r("label",null,[o[1]||(o[1]=w("示例类型",-1)),R(r("select",{class:"select","aria-label":"示例类型","onUpdate:modelValue":o[0]||(o[0]=t=>u.value=t)},[(_(!0),E(v,null,D(c.value,t=>(_(),E("option",{key:t.id,value:t.id},l(t.title),9,O))),128))],512),[[N,u.value]])]),r("p",null,l(i.value?.description),1),A(L,{class:I({"connection-example":e.kind==="business"}),code:i.value?.code||"",language:"python",label:"数据库示例代码"},null,8,["class","code"]),i.value?.note?(_(),E("p",C,l(i.value.note),1)):T("",!0),a.value?(_(),E("p",U,l(a.value),1)):T("",!0),o[2]||(o[2]=r("p",{class:"hint"},"示例仅供复制参考，页面不会执行 SQL。请按实际表结构调整，并在测试库验证。",-1))]))}},F=f(W,[["__scopeId","data-v-96b9beda"]]);export{F as D};
