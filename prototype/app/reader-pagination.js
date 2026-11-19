(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  else root.MemoirPagination=api;
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  'use strict';
  // A fitting function measures actual browser type. Chunks use Unicode code points.
  // hasFigure(section): 그 문단 뒤에 그림(사진 · 삽화)이 있으면, 글을 다 놓은 뒤 그림만 든 칸({figure:true})을 따로 놓는다.
  //   남은 자리에 들어가면 같은 쪽에, 아니면 다음 쪽 맨 위에 — 글자 하나가 그림에 끌려 넘어가지 않는다.
  function paginate(paragraphs,fits,hasFigure){
    const pages=[];
    let page=[];
    paragraphs.forEach((paragraph,section)=>{
      const characters=Array.from(paragraph);
      let start=0;
      while(start<characters.length){
        const block=(length)=>({section,start,end:start+length,text:characters.slice(start,start+length).join('')});
        const rest=block(characters.length-start);
        if(fits([...page,rest])){page.push(rest);start=characters.length;continue;}
        let low=1,high=characters.length-start,best=0;
        while(low<=high){const middle=Math.floor((low+high)/2);if(fits([...page,block(middle)])){best=middle;low=middle+1;}else high=middle-1;}
        if(!best&&page.length){pages.push(page);page=[];continue;}
        const length=best||1;
        page.push(block(length));pages.push(page);page=[];start+=length;
      }
      if(hasFigure&&hasFigure(section)){
        const figure={section,start:characters.length,end:characters.length,text:'',figure:true};
        if(fits([...page,figure]))page.push(figure);
        else{if(page.length)pages.push(page);page=[figure];}
      }
    });
    if(page.length)pages.push(page);
    return pages;
  }
  function characterAtOffset(text,offset){
    const length=Array.from(text||'').length;
    return Math.min(Math.max(0,length-1),Math.max(0,Math.floor(length*(offset||0)+1e-7)));
  }
  function pageForLocation(pages,location,paragraphs){
    const section=Math.max(0,Math.min(paragraphs.length-1,location.section||0));
    const character=characterAtOffset(paragraphs[section],location.offset);
    const found=pages.findIndex(page=>page.some(block=>block.section===section&&block.start<=character&&block.end>character));
    return found<0?Math.max(0,pages.length-1):found;
  }
  function samePassage(first,second,paragraphs,pages){
    if(!first||!second||first.section!==second.section)return false;
    if(pages)return pageForLocation(pages,first,paragraphs)===pageForLocation(pages,second,paragraphs);
    const text=paragraphs[first.section]||'';
    return Math.abs(characterAtOffset(text,first.offset)-characterAtOffset(text,second.offset))<=20;
  }
  function viewState(index,lastIndex,viewSize=1){
    const last=Number.isFinite(lastIndex)?Math.max(0,Math.floor(lastIndex)):0;
    const size=Number.isInteger(viewSize)&&viewSize>0?viewSize:1;
    const target=Number.isFinite(index)?Math.max(0,Math.min(last,index)):0;
    const start=Math.floor(target/size)*size,end=Math.min(start+size-1,last);
    const lastViewStart=Math.floor(last/size)*size;
    return{
      start,end,total:last+1,
      previous:start>0?start-size:null,
      next:end<last?start+size:null,
      percent:lastViewStart?start/lastViewStart*100:100,
    };
  }
  function viewAtPercent(percent,lastIndex,viewSize=1){
    const size=Number.isInteger(viewSize)&&viewSize>0?viewSize:1;
    const lastView=viewState(lastIndex,lastIndex,size);
    const amount=Number.isFinite(percent)?Math.max(0,Math.min(100,percent)):0;
    return Math.round(amount/100*lastView.start/size)*size;
  }
  function sameView(first,second,paragraphs,pages,viewSize=1){
    if(!first||!second)return false;
    const firstIndex=pageForLocation(pages,first,paragraphs)+1;
    const secondIndex=pageForLocation(pages,second,paragraphs)+1;
    return viewState(firstIndex,pages.length,viewSize).start===viewState(secondIndex,pages.length,viewSize).start;
  }
  return{paginate,pageForLocation,characterAtOffset,samePassage,viewState,viewAtPercent,sameView};
});
