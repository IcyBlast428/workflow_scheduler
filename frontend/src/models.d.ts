export type ExecutionStatus = 'queued'|'running'|'success'|'failed'|'timed_out'|'cancelled'|'interrupted'|'skipped'|'missed'|'unknown'|'pending';
export interface TaskRow { id:string; name:string; group_name:string; owner:string; state:string; running_instances:number; max_instances:number; total_failures:number; }
export interface MatrixRecord { key:string; pid:string; run_id:string; status:ExecutionStatus; time:string; count:number; failed:number; start_time:string; end_time:string; }
export interface MatrixSnapshot { date:string; server_time:string; cursor:string; incremental:boolean; removed?:string[]; records:MatrixRecord[]; active:MatrixRecord[]; pending:MatrixRecord[]; }
