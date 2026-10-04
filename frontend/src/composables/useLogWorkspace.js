import { reactive } from 'vue';
import { recentDates } from '../timebase';
export function recentLogDates() {
  return recentDates();
}
export function useLogWorkspace() {
  const dates = recentLogDates();
  const taskLogs = reactive({cursors:[''],nextCursor:'',hasMore:false,loading:false,error:'',rows:[],total:0,ids:[],
    params:{scope:'online',taskid:'',taskname:'',taskstate:'',startDate:dates.start,endDate:dates.end,currentPage:1,pagesize:10}});
  const systemLogs = reactive({hasMore:false,loading:false,error:'',rows:[],total:0,ids:[],params:{systemids:'',startDate:'',endDate:'',currentPage:1,pagesize:10}});
  return {taskLogs,systemLogs};
}
