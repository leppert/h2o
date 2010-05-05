class QuestionInstance < ActiveRecord::Base
  include AuthUtilities
  acts_as_authorization_object

  FEATURED_QUESTION_COUNTS = [[2,2],[4,4],[6,6],[8,8],[10,10]]

#  belongs_to :project
  belongs_to :user
  has_many :questions, :order => :position, :dependent => :destroy
  acts_as_category :scope => :project

  validates_presence_of :name, :featured_question_count
  validates_uniqueness_of :name
  validates_length_of :name, :in => 1..250
  validates_length_of :password, :maximum => 128, :allow_nil => true
  validates_length_of :description, :maximum => 2000, :allow_nil => true

  validates_inclusion_of :featured_question_count, :in => FEATURED_QUESTION_COUNTS.collect{|c| c[1]}

  validates_numericality_of :parent_id, :children_count, :ancestors_count, :descendants_count, :position, :featured_question_count, :allow_nil => true

  #Get "root" questions in this question instance.
  def question_count
    self.questions.find(:all, :conditions => ['parent_id is null']).length
  end

  def featured_questions(params = {})
    Question.featured(params.merge(:question_instance => self))
  end

  def not_featured_questions(params = {})
    Question.not_featured(params.merge(:question_instance => self))
  end

  # Only used if there's significant tampering.
  def self.default_instance
    self.find(:first)
  end

end
