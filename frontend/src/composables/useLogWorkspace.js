import { reactive } from 'vue';
export function recentLogDates() {
  const end = new Date(), start = new Date(end); start.setDate(start.getDate()-6);
  const format = date => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  return {start:format(start),end:format(end)};
}
export function useLogWorkspace() {
  const dates = recentLogDates();
  const taskLogs = reactive({cursors:[''],nextCursor:'',hasMore:false,loading:false,error:'',rows:[],total:0,ids:[],
    params:{scope:'online',taskid:'',taskstate:'',startDate:dates.start,endDate:dates.end,currentPage:1,pagesize:10}});
  const systemLogs = reactive({hasMore:false,loading:false,error:'',rows:[],total:0,ids:[],params:{systemids:'',startDate:'',endDate:'',currentPage:1,pagesize:10}});
  return {taskLogs,systemLogs};
}
