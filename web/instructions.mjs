// Apply versioned engineer instructions in order, including during a live session.
export class InstructionUpdater {
  constructor({load,append,onReady=()=>{}}) {
    Object.assign(this,{load,append,onReady});
    this.tail=Promise.resolve();this.version='';this.generation=0;
  }
  reset() {this.generation++;this.version='';this.tail=Promise.resolve();}
  apply(force=false) {
    this.onReady(false);
    const generation=this.generation;
    const job=this.tail.catch(()=>{}).then(async()=>{
      if(generation!==this.generation)return;
      const catalog=await this.load();
      if(generation!==this.generation)return;
      if(force || catalog.version!==this.version) {
        for(const instruction of catalog.instructions) {
          if(generation!==this.generation)return;
          await this.append(instruction);
        }
        if(generation!==this.generation)return;
        this.version=catalog.version;
      }
      this.onReady(true);
    });
    this.tail=job;return job;
  }
}
