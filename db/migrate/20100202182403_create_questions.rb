require 'migration_helpers'
class CreateQuestions < ActiveRecord::Migration
  def self.up
    extend MigrationHelpers
    create_table :questions do |t|
      t.references :question_instance
      t.integer :user_id
      t.string :question, :limit => 10000, :null => false
      t.boolean :sticky, :default => false
      t.integer :parent_id, :children_count, :ancestors_count, :descendants_count, :position
      t.boolean :hidden

      t.timestamps
    end

    create_foreign_key(Question,QuestionInstance)

    [:user_id, :question_instance_id, :parent_id, :position, :sticky, :updated_at, :created_at].each do |col|
      add_index :questions, col
    end
  end

  def self.down
    drop_table :questions
  end
end
