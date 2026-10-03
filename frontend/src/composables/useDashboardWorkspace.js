import { reactive } from 'vue';
export function useDashboardWorkspace() {
  return reactive({loading:false,loaded:false,error:'',summary:{total:0,running:0,pending:0,paused:0,stopped:0,invalid:0,failed_jobs:0},
    scheduler:{enabled:false,control_url:'',job_count:0},trend:[],failure_rank:[],recent_runs:[],
    cpu_timeline:{samples:[],markers:[],current:null,current_memory:null,sample_interval_seconds:5,retention_hours:6,warning:''},warning:''});
}
